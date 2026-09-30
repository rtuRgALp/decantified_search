# Delivery workflow

For user-requested site changes, implement the change, perform proportionate local verification, commit the task's changes, and push to `origin/main` unless the user explicitly requests local-only work, a different branch, or a pull request.

Pushing to `main` publishes through Cloudflare Pages. After pushing, wait for deployment and smoke-test the affected user journey at https://scent-compass.pages.dev. Report the commit, deployment outcome, and verification result. If deployment or verification cannot be completed, state that limitation clearly.

Stage only files belonging to the current task. Preserve unrelated user changes. Never force-push or discard changes. If remote changes prevent a normal push, inspect and resolve safely; ask the user only when a conflict requires a material choice.
