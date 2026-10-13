# Store session cookies in plaintext files, no keyring in v1

Session files hold the Service's session cookie, which is a bearer credential, and are stored as plaintext in the platform state directory with `0600` file and `0700` directory permissions (the user profile's default ACL on Windows). We rejected OS keyrings (`keyring`) for v1 because they add heavy dependencies and fail in headless and CI environments, and the passwords are never stored, so the exposure is limited to a revocable, expiring session. Revisit if keyring support becomes a requirement.
