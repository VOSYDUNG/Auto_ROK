# Local DeepSeek Harness integration for GPT-OSS

M1 uses DeepSeek Harness as the fair agentic wrapper for GPT-OSS on this Windows machine. Direct `/v1/chat/completions` trials remain useful transport evidence, but they are not comparable to agent runs until the same tool loop, source package, timeout, transcript, and acceptance gates are used.

## Local runtime target

Current local evidence:

- repo workspace: `C:\Shin\CEO-OS\LLM-LOCAL`
- Node: `C:\Program Files\nodejs\node.exe`
- llama.cpp server binary: `C:\Users\PC\AppData\Local\Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe\llama-server.exe`
- GPT-OSS weights: `C:\AI\models\gpt-oss-20b\gpt-oss-20b-MXFP4.gguf`
- Qwen weights: `C:\AI\models\qwen3-coder-30b\Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf`
- local endpoint target: `http://127.0.0.1:8080/v1`
- expected model id: `gpt-oss-20b`
- expected context window: `32768`

Current local status after the user started services: `http://127.0.0.1:8080/v1/models` exposes `gpt-oss-20b` with `n_ctx=32768`, `/slots` reports one idle slot, and `npx --yes --offline @deepseek-ai/dsh --profile headless --help` exits 0. The repo-local patch is `config/dsh-windows-local.patch.yml`. The current contract is ready, but the GPT-OSS smoke has not run yet.

## Historical reference only

An older AIOS run showed a compatible shape:

- DSH package: `@deepseek-ai/dsh` version `0.1.5-rc.1`
- profile bundle: `@deepseek-ai/dsh-sdk-minimal`
- local adapter package: `@deepseek-ai/dsh-llm-pi-ai`
- provider id: `local-gptoss`
- model id: `gpt-oss-20b`
- profile behavior: disable DeepSeek cloud adapter, route an OpenAI-compatible adapter to llama.cpp, and set workspace-write sandbox rooted at the candidate cwd.

That evidence is not the runtime for this repo. The AIOS smoke job created during this turn was cancelled while still queued after the user clarified that M1 must run on this machine.

## Local smoke contract

Repo-local files:

- manifest: `config\deepseek-harness.json`
- packager: `scripts\prepare_dsh_windows.py`
- validator: `src\dsh_windows.py`
- prompt: `config\dsh-smoke-prompt.md`
- DSH CLI: `npx.cmd --yes --offline @deepseek-ai/dsh --profile headless`
- profile patch: `config\dsh-windows-local.patch.yml`
- candidate workspace: `workspace\runs\m1-gptoss-dsh-windows-smoke-001`
- transcript: `workspace\runs\m1-gptoss-dsh-windows-smoke-001\transcript.jsonl`
- output files: `handoff.md` and `metrics-note.json`
- marker: `M1_DSH_GPTOSS_WINDOWS_SMOKE`
- command timeout: `900` seconds
- max tokens: `2048`

The packager does not execute the model. It emits a blocked or ready contract. It only emits a command array when the candidate is marked `experiment=true`, the model is a candidate in `config/models.json`, the endpoint is HTTP loopback `/v1`, paths stay under the repo, runtime/profile/prompt/runner hashes match, the candidate workspace is fresh, and telemetry fields are complete.

## Local command shape

```powershell
python scripts\prepare_dsh_windows.py --output workspace\evidence\m1-dsh-windows-contract.json
```

With the current local state this command returns ready and writes a `launch_contract`. Root should treat that as a smoke-run handoff, not as acceptance of GPT-OSS capability.

## Measurement contract

Every DSH run imported into this repo should record:

- model id, provider id, endpoint host, context window and max output tokens
- harness version, profile path, runner path and trusted hashes
- prompt path, source package hash and candidate cwd
- wall time, exit code, timeout status and finish status
- transcript path, tool call count, files read, files written and changed file list
- public validator result and hidden acceptance result
- compiler time, reviewer time, repair count and escalation result
- money, quota and energy fields as `null` until measured from their own sources

## Safety boundary

The harness may allow a persistent shell inside the candidate workspace. M1 treats that as a sandboxed benchmark tool rooted under `workspace\runs\<run-id>`, not as permission to mutate the Windows repo broadly. Candidate instructions ban internet, package installation, hidden acceptance access and arbitrary generated-code execution unless a later package explicitly authorizes a stronger autonomy level.

Local GPT-OSS remains a candidate worker until M1 can show accepted packages under this harness. It is not yet a planner, reviewer or production committer.
