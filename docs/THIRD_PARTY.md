# Research data attribution

LocalLens source code is MIT licensed. Referenced benchmark datasets, papers, task instructions and implementations retain their original licenses and attribution.

- Terminal-Bench 2.0: [Harbor Framework / original Laude Institute task repository](https://github.com/harbor-framework/terminal-bench-2), Apache License 2.0. The published task inventory is derived from its pinned configuration files. `dashboard/research/controls.json` includes the original `openssl-selfsigned-cert` task instruction, authored by Junhong Shen according to its task metadata, alongside our recorded control results. The license is taken from upstream commit `2fd12b88aafdd04a52c298e3940bcb189f9766d6` (the older task revision has no root license file). A copy is at [dashboard/research/TERMINAL-BENCH-LICENSE.txt](../dashboard/research/TERMINAL-BENCH-LICENSE.txt). No upstream task code or instruction was modified.
- HumanEval: [OpenAI human-eval](https://github.com/openai/human-eval), MIT license. Source data are downloaded locally, not bundled in the website.
- GSM8K: [OpenAI grade-school-math](https://github.com/openai/grade-school-math), MIT license. Source data are downloaded locally, not bundled in the website.
- MBPP and IFEval: [Google Research](https://github.com/google-research/google-research), with upstream repository and dataset terms applying. Source data are downloaded locally, not bundled in the website.
- GLM reference scores: attributed numerical observations from [Z.ai’s GLM-5.3 release](https://z.ai/blog/glm-5.3), linked with a review date and short protocol notes. These are not LocalLens measurements or an endorsement.
- The user-supplied Terminal-Bench PDF is not redistributed in the repository. The dashboard links its public arXiv record.
