## ADDED Requirements

### Requirement: Log access is a documented, conscious trade-off

tjor SHALL ship an exfiltration-conscious investigation-profile guide covering, at minimum: a strict-allow minimal-egress checklist for sessions that read workload logs (`pods/log`), the RBAC posture (view-level access with `secrets` excluded and `pods/log` named explicitly), and an explicit residual-risk statement that content read into the session reaches every remaining allowed egress destination — including the inference endpoint — by design. The kube-broker documentation SHALL reference this guide wherever granting log access is described, so the grant is a conscious choice rather than an assumed-safe default.

#### Scenario: Guide ships and is referenced
- **WHEN** the documentation lint runs
- **THEN** the investigation-profile guide exists and the kube-broker documentation references it

#### Scenario: Residual risk is stated, not implied
- **WHEN** an operator reads the guide before granting `pods/log`
- **THEN** it states plainly that no egress control can prevent read content from reaching the allowed inference endpoint or the human-visible transcript
