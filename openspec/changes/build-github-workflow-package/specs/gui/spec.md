## ADDED Requirements

### Requirement: Root helper invocation works in the frozen (PyInstaller) environment
The GUI's root-privilege delegation (`gui/rootops._helper_module()`) SHALL work both in the dev environment and when the application is frozen by PyInstaller. In the dev environment it SHALL continue to invoke `sys.executable -m systemimgkit.root_helper` (unchanged). In the frozen environment, where `sys.executable` is the frozen GUI executable and `-m` cannot import packaged modules, it SHALL instead invoke the sibling frozen `root_helper` executable located in the same directory as the GUI executable (resolved via `os.path.dirname(sys.executable)`), detected with `getattr(sys, "frozen", False)`. This is required so the `pkexec → root_helper → mke2fs/e2fsdroid` chain does not break after packaging, which would leave the GUI unable to unpack or pack images.

#### Scenario: Dev environment unchanged
- **WHEN** the GUI runs from source (not frozen)
- **THEN** `_helper_module()` returns `[sys.executable, "-m", "systemimgkit.root_helper"]`, identical to the pre-change behavior

#### Scenario: Frozen environment invokes the sibling executable
- **WHEN** the GUI runs as a PyInstaller-frozen executable (`sys.frozen` is true)
- **THEN** `_helper_module()` returns the path to the sibling `root_helper` executable in the same directory as the frozen GUI, and `pkexec` launches it successfully to perform root-gated unpack/pack

#### Scenario: Missing helper surfaces a clear error
- **WHEN** the frozen GUI resolves the helper path but the `root_helper` executable does not exist at the expected location
- **THEN** the GUI surfaces a clear error indicating the bundled root helper is missing, rather than failing opaquely inside pkexec
