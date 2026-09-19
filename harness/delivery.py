"""Publish a verified delivery card to the task and associated pull requests."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import urllib.request


def api(path, method="GET", body=None):
    args = ["gh", "api", "--method", method, path]
    if body is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def card(result, base, evidence, repo, run_url):
    sha = result["sha"]
    body = ["<!-- harness-delivery:" + str(result["task"]) + ":" + result.get("scope", "main") + " -->",
            "## 本轮交付与验证", "",
            f"代码版本：[`{sha[:12]}`](https://github.com/{repo}/commit/{sha}) · [执行记录]({run_url})", "",
            "<details><summary>开发记录（不作为验收结论）</summary>", "", result["summary"], "", "</details>", "",
            "**自动检查：" + ("通过" if evidence["passed"] else "失败") +
            f"**，共 {len(evidence.get('performed', []))} 个操作与断言。人工验收：待确认。", "",
            f"[查看验证记录]({base}browser.json)", ""]
    for title, filename in result.get("screenshots", []):
        body += [f"### {title}", f"![{title}]({base}{filename})", ""]
    if result.get("preview_kind") == "static-web":
        body += [f"**[打开本轮应用]({base})**", "", "此产品是静态应用，数据保存在各自浏览器中。", ""]
    body += ["截图、报告与产物对应上述代码版本；自动检查不替代人工验收。", ""]
    if result.get("experiment"):
        body += ["测试分支：`" + result["experiment"] + "`。当前仍需在 Actions 选择同一分支继续反馈；Issue 评论路由尚未接通。"]
    else:
        body += ["在本 Issue 回复 `/harness 修改意见` 可继续。"]
    return "\n".join(body)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    result = json.loads(args.result.read_text())
    repo = os.environ["GITHUB_REPOSITORY"]
    base = args.base_url.rstrip('/') + '/' + result['published_path'] + '/'
    # Verify public resources before advertising them as a usable delivery.
    with urllib.request.urlopen(base + 'browser.json', timeout=30) as response:
        evidence = json.load(response)
    for _, filename in result.get('screenshots', []):
        with urllib.request.urlopen(base + filename, timeout=30) as response:
            if not response.read(8).startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Published screenshot is not a PNG')
    if result.get('preview_kind') == 'static-web':
        with urllib.request.urlopen(base, timeout=30) as response:
            if response.status != 200:
                raise ValueError('Application preview unavailable')
    run_url = f"https://github.com/{repo}/actions/runs/" + os.environ['GITHUB_RUN_ID']
    body = card(result, base, evidence, repo, run_url)
    marker = body.splitlines()[0]
    targets = {result['task']}
    for pr in api(f"repos/{repo}/commits/{result['sha']}/pulls"):
        if pr['state'] == 'open':
            targets.add(pr['number'])
    for target in sorted(targets):
        comments = api(f"repos/{repo}/issues/{target}/comments?per_page=100")
        existing = next((c for c in comments if c['body'].startswith(marker)
                         and c['user']['login'] == 'github-actions[bot]'), None)
        if existing:
            api(f"repos/{repo}/issues/comments/{existing['id']}", 'PATCH', {'body': body})
        else:
            api(f"repos/{repo}/issues/{target}/comments", 'POST', {'body': body})
    print('Verified delivery published to:', sorted(targets))


if __name__ == '__main__':
    main()
