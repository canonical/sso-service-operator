# sso-service-info

The interface library for the `sso_service_info` relation: sso-service's charm publishes its
gRPC address, and the login UI's charm reads it.

It is a Python package that lives in this repository and is not published on Charmhub or PyPI.
A charm that needs it adds it to its dependencies at a commit of this repository:

```
sso-service-info @ git+https://github.com/canonical/sso-service-operator@<commit>#subdirectory=interfaces/sso_service_info
```

and adds `git` to the `build-packages` of its charm part in `charmcraft.yaml`. Usage is in the
module's docstring (`src/sso_service_info/__init__.py`).
