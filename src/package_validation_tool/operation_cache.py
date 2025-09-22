# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Module implementing operation caching"""

import hashlib
import json
import logging
import os
import shutil
from dataclasses import asdict, is_dataclass
from functools import wraps
from typing import Any

log = logging.getLogger(__name__)


def data_to_return_type(func, data: dict):
    """Transform data in dictionary to object of function return type."""
    return_type = func.__annotations__.get("return")
    if return_type and is_dataclass(return_type):
        return return_type(**data)
    return data


def return_type_to_json_dict(result) -> dict:
    """Convert a given return type into a JSON-enabled dictionary."""

    if isinstance(result, dict):
        return result
    return result.to_json_dict()


def generate_hash_metadata(func_name, args, kwargs):
    """Return hash value for function properties, and hash metadata."""

    def obj_to_str(obj):
        """Convert object to string."""
        if isinstance(obj, (int, float, str, bool, type(None))):
            return str(obj)
        elif isinstance(obj, (list, tuple)):
            return ",".join(obj_to_str(item) for item in obj)
        elif isinstance(obj, dict):
            return ",".join(f"{k}:{obj_to_str(v)}" for k, v in sorted(obj.items()))
        elif is_dataclass(obj):
            return f"{obj.__class__.__name__}={obj_to_str(asdict(obj))}"
        elif "__class__" in dir(obj):
            member_list = [a for a in dir(obj) if not callable(getattr(obj, a)) and "__" not in a]
            value_pairs = [f"{a}={obj_to_str(getattr(obj, a))}" for a in member_list]
            return f"{obj.__class__.__name__}={'.'.join(value_pairs)}"
        else:
            return str(obj)

    key_parts = [func_name]
    key_parts.append(obj_to_str(args))
    key_parts.append(obj_to_str(kwargs))

    full_key = "_".join(key_parts)
    hash_suffix = hashlib.sha256(full_key.encode()).hexdigest()

    readable_key = "_".join(p[:8] for p in key_parts if p) + f"_{hash_suffix}"
    readable_key = readable_key.replace(os.path.sep, "_")

    cache_meta_data = {
        "function": func_name,
        "args": obj_to_str(args),
        "kwargs": obj_to_str(kwargs),
    }

    return readable_key, cache_meta_data


def load_return_value_from_cache_file(cache_file: str, func, cache_meta_data: dict) -> dict:
    """Load return value for a function from cache file, if meta data matches."""
    log.debug("Loading cached result for function %s from file %s", func.__name__, cache_file)
    with open(cache_file, "r", encoding="utf-8") as f:
        cached_entry = json.loads(f.read())
    cached_result = data_to_return_type(func, cached_entry["result"])
    if cached_entry["metadata"] != cache_meta_data:
        log.warning("Cached metadata does not match current metadata")
        return None
    return cached_result


def store_return_value_in_cache_file(cache_file: str, func, result, cache_meta_data: dict = None):
    """Store return value for a function in cache file."""
    log.debug(
        "Caching result for function %s to file %s",
        func.__name__,
        cache_file,
    )
    # Create an entry where we can also see the returned values
    cache_entry = {
        "metadata": cache_meta_data,
        "result": return_type_to_json_dict(result),
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(cache_entry, f, indent=2)


class OperationCache:
    """
    Cache the result of operations on disk, to avoid re-running expensive computations.

    When considering objects for hashing, attributes with two consecutive understores '__'
    are not considered. This way, objects can prepared accordingly.
    """

    _instance = None
    _initialized = False

    def __new__(cls, cache_directory: str = None, write_only: bool = False):
        if cls._instance is None:
            cls._instance = super(OperationCache, cls).__new__(cls)
        return cls._instance

    def __init__(self, cache_directory: str = None, write_only: bool = False):
        if not self._initialized:
            self.cache_directory = cache_directory
            self._calls = 0
            self._cached_results = 0
            self._cached_hash_errors = 0
            self._cached_retrieve_errors = 0
            self._cached_store_errors = 0
            self._write_only = write_only
            self._initialized = True

    def __exit__(self, exc_type, exc_value, traceback):
        log.debug("Stopping OperationCache with stats: %s", self.get_cache_stats())

    def call(self, func, *args, **kwargs) -> Any:
        """Execute the function/method with arguments, checking and updating the cache if activated."""
        self._calls += 1

        if self.cache_directory is None:
            return func(*args, **kwargs)

        cache_file = None
        try:
            func_dir = os.path.join(self.cache_directory, func.__name__)
            cache_key, cache_meta_data = generate_hash_metadata(func.__name__, args, kwargs)

            os.makedirs(func_dir, exist_ok=True)
            cache_file = os.path.join(func_dir, f"{cache_key}.json")
        except Exception as e:
            # no real error, as we can still execute the function without caching
            log.debug(
                "Error: Cache failed to generate cache file for %s with exception %s",
                func.__name__,
                e,
            )
            self._cached_hash_errors += 1

        # only try to load from cache if we are not looking for updates only
        if not self._write_only:
            try:
                if cache_file is not None and os.path.exists(cache_file):
                    self._cached_results += 1
                    cached_result = load_return_value_from_cache_file(
                        cache_file=cache_file, func=func, cache_meta_data=cache_meta_data
                    )
                    if cached_result is not None:
                        return cached_result
            except Exception as e:
                # no real error, as we can still execute the function without caching
                log.debug("Error: failed caching function call %s: %s", func.__name__, e)
                self._cached_retrieve_errors = 0

        result = func(*args, **kwargs)

        try:
            if cache_file is not None:
                store_return_value_in_cache_file(
                    cache_file=cache_file, func=func, result=result, cache_meta_data=cache_meta_data
                )
        except Exception as e:
            log.debug("Error: failed caching result for function call %s: %s", func.__name__, e)
            self._cached_store_errors = 0
            shutil.rmtree(cache_file, ignore_errors=True)

        return result

    def clear_cache(self):
        if self.cache_directory and os.path.exists(self.cache_directory):
            for root, dirs, files in os.walk(self.cache_directory, topdown=False):
                for file in files:
                    os.remove(os.path.join(root, file))
                for directory in dirs:
                    os.rmdir(os.path.join(root, directory))
            os.rmdir(self.cache_directory)
        self._calls = 0
        self._cached_results = 0

    def get_cache_stats(self) -> str:
        if self._calls == 0:
            return f"0 calls made yet. Cache directory: {self.cache_directory}"
        percentage = (self._cached_results / self._calls) * 100
        error_message = f"(cache errors: {self._cached_hash_errors} hash, {self._cached_retrieve_errors} retrieve, {self._cached_store_errors} store)"
        return f"From {self._calls} calls, {self._cached_results} have been cached ({percentage:.2f}%), using directory {self.cache_directory} {error_message}."


def initialize_cache(cache_directory: str = None, write_only: bool = False) -> bool:
    log.debug("Initializing OperationCache for directory %s", cache_directory)
    cache = OperationCache(cache_directory=cache_directory, write_only=write_only)
    cache_using_requested_dir = cache.cache_directory != cache_directory
    log.debug(
        "Cache using requested directory: %s (%s)", cache_using_requested_dir, cache_directory
    )
    return cache_using_requested_dir


def disk_cached_operation(func):
    """
    Call function or method, and use cached results if available.

    When considering objects for hashing, e.g. as part of the parameters of the function, the
    object attributes with two consecutive understores '__' are not considered. This way,
    objects can prepared accordingly.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        cache = OperationCache()
        return cache.call(func, *args, **kwargs)

    return wrapper


def cache_stats() -> str:
    cache = OperationCache()
    return cache.get_cache_stats()


def manage_cache(clean: bool = True) -> bool:
    """Perform operations on the Operations cache."""
    cache = OperationCache()
    if clean:
        cache.clear_cache()
    return True
