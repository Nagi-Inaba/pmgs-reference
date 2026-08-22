# CLI JSON implementation application v2

- apply: 0
- sync: 0
- format: 2
- ruff: 1
- mypy: 2
- focused pytest: 2

## apply output

```

```

## ruff output

```
    |

invalid-syntax: Expected `,`, found `:`
   --> src/pmgs_reference/cli.py:811:21
    |
809 |         parser.exit(1, f"error: {exc}
810 | ")
811 |     except Exception:
    |                     ^
812 |         if json_mode:
813 |             return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
    |

invalid-syntax: Expected `,`, found newline
   --> src/pmgs_reference/cli.py:811:22
    |
809 |         parser.exit(1, f"error: {exc}
810 | ")
811 |     except Exception:
    |                      ^
812 |         if json_mode:
813 |             return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
    |

invalid-syntax: Expected `,`, found indent
   --> src/pmgs_reference/cli.py:812:1
    |
810 | ")
811 |     except Exception:
812 |         if json_mode:
    | ^^^^^^^^
813 |             return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
814 |         raise
    |

invalid-syntax: Expected `)`, found `if`
   --> src/pmgs_reference/cli.py:812:9
    |
810 | ")
811 |     except Exception:
812 |         if json_mode:
    |         ^^
813 |             return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
814 |         raise
    |

invalid-syntax: Expected `else`, found `:`
   --> src/pmgs_reference/cli.py:812:21
    |
810 | ")
811 |     except Exception:
812 |         if json_mode:
    |                     ^
813 |             return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
814 |         raise
    |

invalid-syntax: Expected an expression
   --> src/pmgs_reference/cli.py:812:22
    |
810 | ")
811 |     except Exception:
812 |         if json_mode:
    |                      ^
813 |             return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
814 |         raise
    |

invalid-syntax: Unexpected indentation
   --> src/pmgs_reference/cli.py:813:1
    |
811 |     except Exception:
812 |         if json_mode:
813 |             return _emit_failure(command, "INTERNAL_ERROR", "internal operation failed")
    | ^^^^^^^^^^^^
814 |         raise
815 |     parser.error(f"unsupported command: {args.command}")
    |

Found 119 errors.
```

## mypy output

```
src/pmgs_reference/cli.py:190: error: Unterminated f-string literal (detected at line 190)  [syntax]
Found 1 error in 1 file (errors prevented further checking)
```

## focused pytest output

```

==================================== ERRORS ====================================
________________ ERROR collecting tests/test_cli_json_errors.py ________________
.venv/lib/python3.12/site-packages/_pytest/python.py:508: in importtestmodule
    mod = import_path(
.venv/lib/python3.12/site-packages/_pytest/pathlib.py:596: in import_path
    importlib.import_module(module_name)
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
<frozen importlib._bootstrap>:1387: in _gcd_import
    ???
<frozen importlib._bootstrap>:1360: in _find_and_load
    ???
<frozen importlib._bootstrap>:1331: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:935: in _load_unlocked
    ???
.venv/lib/python3.12/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_cli_json_errors.py:9: in <module>
    import pmgs_reference.cli as cli_module
E     File "/home/runner/work/pmgs-reference/pmgs-reference/src/pmgs_reference/cli.py", line 190
E       self.exit(2, f"{self.prog}: エラー: {message}
E                    ^
E   SyntaxError: unterminated f-string literal (detected at line 190)
___________________ ERROR collecting tests/test_cli_query.py ___________________
.venv/lib/python3.12/site-packages/_pytest/python.py:508: in importtestmodule
    mod = import_path(
.venv/lib/python3.12/site-packages/_pytest/pathlib.py:596: in import_path
    importlib.import_module(module_name)
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
<frozen importlib._bootstrap>:1387: in _gcd_import
    ???
<frozen importlib._bootstrap>:1360: in _find_and_load
    ???
<frozen importlib._bootstrap>:1331: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:935: in _load_unlocked
    ???
.venv/lib/python3.12/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_cli_query.py:10: in <module>
    from pmgs_reference import cli as cli_module
E     File "/home/runner/work/pmgs-reference/pmgs-reference/src/pmgs_reference/cli.py", line 190
E       self.exit(2, f"{self.prog}: エラー: {message}
E                    ^
E   SyntaxError: unterminated f-string literal (detected at line 190)
___________________ ERROR collecting tests/test_setup_cli.py ___________________
.venv/lib/python3.12/site-packages/_pytest/python.py:508: in importtestmodule
    mod = import_path(
.venv/lib/python3.12/site-packages/_pytest/pathlib.py:596: in import_path
    importlib.import_module(module_name)
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
<frozen importlib._bootstrap>:1387: in _gcd_import
    ???
<frozen importlib._bootstrap>:1360: in _find_and_load
    ???
<frozen importlib._bootstrap>:1331: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:935: in _load_unlocked
    ???
.venv/lib/python3.12/site-packages/_pytest/assertion/rewrite.py:188: in exec_module
    exec(co, module.__dict__)
tests/test_setup_cli.py:9: in <module>
    import pmgs_reference.cli as cli_module
E     File "/home/runner/work/pmgs-reference/pmgs-reference/src/pmgs_reference/cli.py", line 190
E       self.exit(2, f"{self.prog}: エラー: {message}
E                    ^
E   SyntaxError: unterminated f-string literal (detected at line 190)
=========================== short test summary info ============================
ERROR tests/test_cli_json_errors.py
ERROR tests/test_cli_query.py
ERROR tests/test_setup_cli.py
!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!
3 errors in 0.26s
```
