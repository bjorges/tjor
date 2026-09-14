## 1. Guide + pointers

- [x] 1.1 Write `docs/investigation-profiles.md`: threat framing, the exfiltration-conscious checklist (minimal strict-allow egress, RBAC posture, short TTL, #42 recap review), a worked policy/config example, the explicit residual-risk statement, and the deferred volume-friction note pointing at #50. Verify: content covers every spec-required element.
- [x] 1.2 README kube-broker section: short pointer to the guide for log-granting profiles. Verify: pointer present.

## 2. Lint

- [x] 2.1 `tests/doc_consistency.sh`: add the structural check — `docs/investigation-profiles.md` exists and README references it. Verify: lint green; deleting the pointer makes it fail.

## 3. Docs

- [x] 3.1 CHANGELOG entry under Unreleased (#50). Verify: entry present, style-consistent.
