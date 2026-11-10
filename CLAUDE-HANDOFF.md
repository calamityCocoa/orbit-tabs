# Orbit Tabs handoff

Review the monitor wall and the answer, delay, and submit flow. Run `python -m unittest discover -s tests -v` in an environment with PySide6 and a graphical session.

Use the local quiz fixture to verify that answers are entered first, Submit waits for both the configured delay and the enabled button, and each attempt sends exactly one request. Report any issues before changing live Orbit behavior.

The Windows x64 portable build is in `dist/`. The setup guide is `README.md`.
