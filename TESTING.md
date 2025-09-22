## Unit Tests (Pytest)

Our project uses Pytest framework:

```sh
# Install pytest prerequisites
yum install python3-pytest python3-pytest-cov

# Run all tests
pytest

# Run all test cases in test_matching.py
pytest test/test_matching.py

# Run all test cases in test_matching.py and show all logs
pytest -vv --capture=no --log-cli-level=NOTSET test/test_matching.py

# Run a single test case
pytest test/test_matching.py::test_identical_strings
```

## System Level Tests

In the `test/` directory there are scripts to run basic system level testing.
The scripts can be executed without parameters to run the tests.

```
test/system-level-testing.sh ... to execute typical use cases in the current
                                 environment, to notice breaking changes early.

test/docker-testing.sh ......... to check building the docker environment, and
                                 then run the system-level-testing.sh in the
                                 created docker container.
```

## Runtime Settings

The tool recognizes the following environment variables:

- `PYTHON_SOCKET_TIMEOUT`: timeout for all networking operations such as
  connect, send and receive; in seconds. Default value is 10 seconds. Typically
  there is no need to tune this setting, but can be useful for experimentation
  and debugging.

