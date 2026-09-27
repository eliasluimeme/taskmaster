# 42 Taskmaster - Defense & Evaluation Guide

This document provides a step-by-step walkthrough to demonstrate all mandatory features and bonuses during the 42 peer-evaluation defense session.

---

## 1. Setup & Compilation

```bash
# 1. Activate virtual environment
source .venv/bin/activate

# 2. Compile mock C programs used for edge-case testing
make -C tests/programs

# 3. Run automated test suite (39 tests)
pytest -v
```

---

## 2. Mandatory Part Walkthrough

### Test 1: Launching Taskmaster & Foreground Control Shell
```bash
# Launch Taskmaster with demo configuration
taskmaster -c demo.yml
```
- Verify the interactive prompt appears: `taskmaster> `
- Test command auto-completion: type `st` and press `Tab` -> completes to `status` / `start`
- Verify history: use `Up` / `Down` arrows to navigate previous commands.

---

### Test 2: Process Status Verification ("status" command)
In the shell, run:
```text
taskmaster> status
```
- Observe the tabular output:
  - `worker:0` and `worker:1` are in state **`RUNNING`** with their PIDs and uptimes (autostart was `true`).
  - `crasher`, `stubborn`, and `flooder` are in state **`STOPPED`**.

---

### Test 3: Manually Killing a Supervised Process
The subject requires Taskmaster to know at all times if processes are alive or dead.
1. Note the PID of `worker:0` from `status` (e.g. `29384`).
2. Open a separate terminal and kill the child process forcefully:
   ```bash
   kill -9 <PID>
   ```
3. Return to the Taskmaster shell and check status:
   ```text
   taskmaster> status
   ```
4. Observe that Taskmaster immediately detected the termination:
   - Because `autorestart: unexpected` is set, Taskmaster automatically restarted `worker:0` with a fresh PID!
   - Inspect the log file to verify the audit event:
     ```text
     taskmaster> tail worker stdout
     ```

---

### Test 4: Launching Processes That Fail / Crash Repeatedly
The subject requires testing processes that never start correctly.
```text
taskmaster> start crasher
```
1. Observe the real-time logging and status:
   - `crasher` exits immediately with returncode 1 (before `starttime: 2s` elapses).
   - Taskmaster transitions `crasher` into **`BACKOFF`** and waits with an incremental delay before retrying.
2. Check `status` after retries are exhausted (`startretries: 2`):
   ```text
   taskmaster> status crasher
   ```
   - State transitioned to **`FATAL`**. Taskmaster cleanly ceases restart attempts without crashing or freezing.

---

### Test 5: Graceful Stop with SIGKILL Fallback
The subject tests graceful stopping and fallback to forceful termination if unresponsive.
```text
taskmaster> start stubborn
taskmaster> status stubborn
```
1. `stubborn` is now `RUNNING`. This process catches and ignores `SIGTERM`.
2. Stop the process:
   ```text
   taskmaster> stop stubborn
   ```
3. Taskmaster sends `SIGTERM` and waits for `stoptime: 3s`.
4. After 3 seconds, Taskmaster detects that the process is still alive and issues **`SIGKILL`**.
5. Check status:
   ```text
   taskmaster> status stubborn
   ```
   - State is cleanly transitioned to **`STOPPED`**.

---

### Test 6: Heavy Output Generation (stdout/stderr redirection)
```text
taskmaster> start flooder
```
1. Observe that Taskmaster handles heavy stream output smoothly without hanging or blocking the event loop.
2. Inspect the captured output:
   ```text
   taskmaster> tail -n 10 flooder stdout
   taskmaster> tail -n 10 flooder stderr
   ```

---

### Test 7: Zero-Downtime Hot Reloading (SIGHUP and reload)
The subject strictly requires:
> *"When it is reloaded, your program is expected to effect all the necessary changes to its run state... but it must NOT de-spawn processes that haven't been changed in the reload."*

1. Run `status` and note the PIDs of `worker:0` and `worker:1`:
   ```text
   taskmaster> status worker
   ```
2. In another terminal, edit `demo.yml`:
   - Change `worker` `numprocs` from `2` to `3`.
   - Change `crasher` `startretries` from `2` to `5`.
3. In Taskmaster, trigger reload:
   ```text
   taskmaster> reload
   # Or send SIGHUP from another terminal: kill -HUP <taskmaster_pid>
   ```
4. Check status:
   ```text
   taskmaster> status
   ```
   - **Verification**: The PIDs of `worker:0` and `worker:1` are **identical** to before the reload! They were never killed or interrupted!
   - A new instance `worker:2` was created and spawned seamlessly.

---

### Test 8: Clean Supervisor Shutdown
```text
taskmaster> quit
```
- Taskmaster gracefully terminates all child processes before exiting.
- Confirm with `ps aux | grep sleeper` that no zombie or orphan processes remain.

---

## 3. Bonus Part: Client/Server Architecture

Taskmaster provides a full daemon (`taskmasterd`) and remote client (`taskmasterctl`) communicating over a UNIX domain socket (`/tmp/taskmaster.sock`):

### Running the Daemon
```bash
taskmasterd -c demo.yml
```
- Runs the supervisor engine as a daemon in the background or headless mode.
- Creates the IPC socket `/tmp/taskmaster.sock`.

### Interacting via the Client CLI (`taskmasterctl`)

1. **One-shot command mode:**
   ```bash
   taskmasterctl status
   taskmasterctl start stubborn
   taskmasterctl stop stubborn
   ```

2. **Interactive client shell mode:**
   ```bash
   taskmasterctl
   taskmasterctl> status
   taskmasterctl> reload
   taskmasterctl> quit   # Exits taskmasterctl shell (daemon remains running)
   ```

3. **Shutting down the remote supervisor daemon:**
   ```bash
   taskmasterctl shutdown
   # Or inside interactive shell:
   taskmasterctl> shutdown
   ```

