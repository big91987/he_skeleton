# Project worker instructions

Read `docs/00-global/project.md` and the current task before working. Follow the product scope and existing code. Use the native stage Skills as needed, without copying their full text into prompts.

The light workflow resumes one Codex Session per Issue. Requirements, design and development are separate Jobs. Each active Job gets one execution with only its own native Skill catalog. Answer, clarify, edit or continue within the current stage. Request human confirmation of requirements and design documents; after clear confirmation, return the adjacent next stage and let its Job resume the same Session to work. Do not reuse that confirmation to approve the next stage’s documents. Approval belongs in runtime state, not document prose.

Communicate directly with the user: before working, briefly say which stage you are in and what you will do with their request. Share meaningful progress, findings or blockers as needed. Use commentary for these messages and reserve the three-field JSON for the final result. Tool calls stay in Actions logs; your progress messages accumulate in a collapsed Issue comment, followed by a separate final reply. Choose useful wording and timing instead of repeating a fixed status template.

Never fabricate verification or change managed execution rules. Fix reusable tools upstream. Run project checks and format/lint before declaring delivery. Keep credentials and private sessions out of Git.

See [the light workflow](docs/harness-light.md). Owner configuration: `.harness/full.json`.
