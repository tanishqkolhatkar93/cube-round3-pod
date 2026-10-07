# How to use this repository

This repo is the official starting point for **03 · Pack Manager**.

Round 2 is an **individual build**, and each participant works in their **own GitHub fork**. That keeps each participant's development and final submission separate.

The workflow is:

```text id="b9t9dl"
Official Repository
        ↓
      Fork
        ↓
 Your GitHub Fork
        ↓
 Build + Test
        ↓
 Commit + Push
        ↓
 Final Submission
```

**New here?** Read these first:

1. [`README.md`](README.md) explains the Pack Manager problem, data and build expectations.
2. [`RULES.md`](RULES.md) covers the repository and engineering rules.

---

## 0. One-time setup

You need `git` installed and a GitHub account.

Set your identity once, if you haven't before:

```sh id="v7ed9l"
git config --global user.name  "Your Name"
git config --global user.email "you@example.com"   # use the email on your GitHub account
```

If you use SSH, check it works with:

```sh id="5qf17z"
ssh -T git@github.com
```

If you'd rather use HTTPS, the easiest way to sign in is the GitHub CLI:

```sh id="w7h3f5"
gh auth login
```

---

## 1. Fork the repo

Open the official repository:

```text id="m9et4g"
https://github.com/Cube-Build-A-Thon/cube-03-pack-manager
```

Click **Fork** and create a copy under your own GitHub account.

Your fork is your Round 2 development and submission repository.

---

## 2. Clone your fork

Clone **your fork**, not the organiser repository.

### SSH

```sh id="f3e0j1"
git clone git@github.com:<your-github-username>/cube-03-pack-manager.git
cd cube-03-pack-manager
```

### HTTPS

```sh id="n40kq7"
git clone https://github.com/<your-github-username>/cube-03-pack-manager.git
cd cube-03-pack-manager
```

Replace `<your-github-username>` with your GitHub username.

---

## 3. Start building

You do **not** need to create a participant folder or a participant branch in the organiser repository.

Build your Pack Manager directly inside your own fork.

You may organise your application however you prefer.

A simple development flow is:

```text id="u6a3qk"
Understand
    ↓
Build
    ↓
Test
    ↓
Evaluate
    ↓
Document
    ↓
Demo / Deploy
    ↓
Submit
```

See [`README.md`](README.md) for the Pack Manager requirements.

---

## 4. Commit and push, often

Commit your work regularly.

For example:

```sh id="b2v0cg"
git status
git add .
git commit -m "Implement pack verification"
git push origin main
```

You may also create your own development branches inside your fork if you prefer:

```sh id="d57xkn"
git checkout -b feature/pack-verification
```

After the first push, `git push` is enough when your upstream branch is configured.

Use meaningful commit messages, for example:

```text id="m0e6qh"
Implement order-line matching
Add quantity verification
Add extra-item detection
Add SEAL and STOP_AND_FIX decisions
Add uncertainty handling
Add evaluation metrics
```

Avoid unclear messages such as:

```text id="a6fd9c"
update
changes
final
final2
fix
```

### Build-phase commit rule

All code commits forming your Round 2 submission must be made during the **authorised build phase**.

Round 2 build begins:

**25 September 2026 · 9:00 AM IST**

Once the build phase ends, do not continue making Round 2 code changes.

---

## 5. Keep your fork clean

Your final fork should contain the complete Pack Manager implementation and the documentation required for submission.

You are responsible for your own:

* code,
* tests,
* evaluation,
* documentation,
* deployment,
* and final repository.

Do not modify or interfere with the organiser's official repository or another participant's work.

---

## 6. What happens next

There is no PR-to-main workflow for your Round 2 submission.

You build and push to **your own fork**.

When the submission window opens, you submit the URL of your final fork through the official Cube Buildathon submission form.

### Important dates

* **Build starts:** 25 September 2026 · 9:00 AM IST
* **Submissions open:** 27 September 2026
* **Final submission deadline:** 1 October 2026 · 6:00 PM IST

The submission form closes permanently at the deadline.

**There is no resubmission.**

---

## 7. Asking for help, or reporting a problem

* **Something in the shared data or docs is wrong or contradicts itself:** raise it with the organisers and identify it as a `finding`. Do not silently change the official repository.
* **Access or permission problems:** check that you are signed in to the GitHub account that owns your fork, or contact an organiser.
* **Questions about integration with the other Managers:** use the official Buildathon communication channels and evidence-contract guidance provided by the organisers.

---

## Common problems

| Symptom                         | Fix                                                                                               |
| ------------------------------- | ------------------------------------------------------------------------------------------------- |
| `remote: Repository not found`  | Check that you cloned your own fork and that the repository URL is correct.                       |
| `remote: Permission denied`     | Make sure you are authenticated to the GitHub account that owns your fork.                        |
| Push rejected                   | Check your branch, run `git pull` if needed, resolve any conflicts, then push again.              |
| `rejected ... (fetch first)`    | Run `git pull --rebase`, resolve any conflicts, then `git push`.                                  |
| Merge conflict                  | Open the affected file, resolve the conflict, then `git add` and `git commit`.                    |
| Environment not working         | Check the README setup instructions, dependencies and environment variables.                      |
| Accidentally committed a secret | **Revoke the credential immediately**, then remove it from the repository history as appropriate. |

---

## Commands you'll use every day

```sh id="3sc8b9"
git status                              # what changed
git add .                              # stage changes
git commit -m "..."                    # commit changes
git push                               # push to your fork
git pull --rebase                      # update your local branch
git log --oneline -10                  # recent history
```

If you use your own development branch:

```sh id="9nc9pu"
git checkout -b feature/my-change
git push -u origin feature/my-change
```

---

## Before you submit

Make sure:

```text id="ez5f0n"
[ ] Working Pack Manager
[ ] Working in my own GitHub fork
[ ] Required code commits completed during the authorised build phase
[ ] README.md complete
[ ] RULES.md reviewed
[ ] ARCHITECTURE.md complete
[ ] Evaluation completed
[ ] Demo ready
[ ] Deployment URL verified, if applicable
[ ] LinkedIn post published
[ ] CodeQuesters tagged
[ ] Sydon.AI tagged
[ ] Submission links verified
[ ] Ready before 1 October 2026 · 6:00 PM IST
```

**Cube Buildathon · 03 · Pack Manager**
