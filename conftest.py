import os
from uuid import uuid1

import pytest

from hub.constants import (
    MIN_SECOND_CACHE_SIZE,
    MIN_FIRST_CACHE_SIZE,
    PYTEST_LOCAL_PROVIDER_BASE_ROOT,
    PYTEST_MEMORY_PROVIDER_BASE_ROOT,
    PYTEST_S3_PROVIDER_BASE_ROOT,
)
from hub.core.storage import LocalProvider, MemoryProvider, S3Provider
from hub.core.tests.common import LOCAL, MEMORY, S3
from hub.tests.common import SESSION_ID, current_test_name
from hub.util.cache_chain import get_cache_chain

MEMORY_OPT = "--memory-skip"
LOCAL_OPT = "--local"
S3_OPT = "--s3"
CACHE_OPT = "--cache-chains"
CACHE_ONLY_OPT = "--cache-chains-only"
S3_BUCKET_OPT = "--s3-bucket"


def _get_storage_configs(request):
    return {
        MEMORY: {
            "base_root": PYTEST_MEMORY_PROVIDER_BASE_ROOT,
            "class": MemoryProvider,
            "use_id": False,
            "is_id_prefix": False,  # if is_id_prefix (and use_id=True), the session id comes before test name, otherwise it is reversed
        },
        LOCAL: {
            "base_root": PYTEST_LOCAL_PROVIDER_BASE_ROOT,
            "class": LocalProvider,
            "use_id": False,
            "is_id_prefix": False,
        },
        S3: {
            "base_root": request.config.getoption(S3_BUCKET_OPT),
            "class": S3Provider,
            "use_id": True,
            "is_id_prefix": True,
        },
    }


def _skip_if_none(val):
    if val is None:
        pytest.skip()


def _is_opt_true(request, opt):
    return request.config.getoption(opt)


def pytest_addoption(parser):
    parser.addoption(
        MEMORY_OPT,
        action="store_true",
        help="Tests using the `memory_provider` fixture will be skipped. Tests using the `storage` fixture will be skipped if called with \
                `MemoryProvider`.",
    )
    parser.addoption(
        LOCAL_OPT,
        action="store_true",
        help="Tests using the `storage`/`local_provider` fixtures will run with `LocalProvider`.",
    )
    parser.addoption(
        S3_OPT,
        action="store_true",
        help="Tests using the `storage`/`s3_provider` fixtures will run with `S3Provider`.",
    )
    parser.addoption(
        CACHE_OPT,
        action="store_true",
        help="Tests using the `storage` fixture may run with combinations of all enabled providers \
                in cache chains. For example, if the option `%s` is not provided, all cache chains that use `S3Provider` are skipped."
        % (S3_OPT),
    )
    parser.addoption(
        CACHE_ONLY_OPT,
        action="store_true",
        help="Force enables `%s`. `storage` fixture only returns cache chains. For example, if `%s` is provided, \
            `storage` will never be just `S3Provider`."
        % (CACHE_OPT, S3_OPT),
    )
    parser.addoption(
        S3_BUCKET_OPT,
        type=str,
        help="Url to s3 bucket with optional key. Example: s3://bucket_name/key/to/tests/",
        default=PYTEST_S3_PROVIDER_BASE_ROOT,
    )


def _get_storage_provider(request, storage_name, with_current_test_name=True):
    info = _get_storage_configs(request)[storage_name]
    root = info["base_root"]
    if with_current_test_name:
        path = current_test_name(
            with_id=info["use_id"], is_id_prefix=info["is_id_prefix"]
        )
        root = os.path.join(root, path)
    return info["class"](root)


def _get_memory_provider(request):
    return _get_storage_provider(request, MEMORY)


def _get_local_provider(request):
    return _get_storage_provider(request, LOCAL)


def _get_s3_provider(request):
    return _get_storage_provider(request, S3)


@pytest.fixture
def memory_storage(request):
    if not _is_opt_true(request, MEMORY_OPT):
        return _get_memory_provider(request)


@pytest.fixture
def local_storage(request):
    if _is_opt_true(request, LOCAL_OPT):
        return _get_local_provider(request)


@pytest.fixture
def s3_storage(request):
    if _is_opt_true(request, S3_OPT):
        return _get_s3_provider(request)


@pytest.fixture
def storage(request, memory_storage, local_storage, s3_storage):
    requested_providers = request.param
    if isinstance(requested_providers, str):
        requested_providers = (requested_providers,)

    # --cache-chains-only force enables --cache-chains
    use_cache_chains_only = _is_opt_true(request, CACHE_ONLY_OPT)
    use_cache_chains = _is_opt_true(request, CACHE_OPT) or use_cache_chains_only

    if use_cache_chains_only and len(requested_providers) <= 1:
        pytest.skip()

    if not use_cache_chains and len(requested_providers) > 1:
        pytest.skip()

    storage_providers = []
    cache_sizes = []

    if MEMORY in requested_providers:
        _skip_if_none(memory_storage)
        storage_providers.append(memory_storage)
        cache_sizes.append(MIN_FIRST_CACHE_SIZE)
    if LOCAL in requested_providers:
        _skip_if_none(local_storage)
        storage_providers.append(local_storage)
        cache_size = MIN_FIRST_CACHE_SIZE if not cache_sizes else MIN_SECOND_CACHE_SIZE
        cache_sizes.append(cache_size)
    if S3 in requested_providers:
        _skip_if_none(s3_storage)
        storage_providers.append(s3_storage)

    if len(storage_providers) == len(cache_sizes):
        cache_sizes.pop()

    return get_cache_chain(storage_providers, cache_sizes)


@pytest.fixture(scope="session", autouse=True)
def clear_storages(request):
    # executed before the first test

    if not _is_opt_true(request, MEMORY_OPT):
        storage = _get_storage_provider(request, MEMORY, with_current_test_name=False)
        storage.clear()

    if _is_opt_true(request, LOCAL_OPT):
        storage = _get_storage_provider(request, LOCAL, with_current_test_name=False)
        storage.clear()

    # don't clear S3 tests (these will be automatically cleared on occasion)

    yield

    # executed after the last test

    if _is_opt_true(request, S3_OPT):
        # s3 is the only storage provider that uses the SESSION_ID prefix
        # if it is enabled, print it out after all tests finish
        print("\n\n")
        print("----------------------------------------------------------")
        print("Testing session ID: %s" % SESSION_ID)
        print("----------------------------------------------------------")
