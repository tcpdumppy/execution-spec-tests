"""
Test good and bad EOFCREATE cases
"""

import pytest

from ethereum_test_tools import (
    Account,
    Environment,
    StateTestFiller,
    TestAddress,
    compute_eofcreate_address,
)
from ethereum_test_tools.eof.v1 import Container, Section
from ethereum_test_tools.eof.v1.constants import (
    MAX_BYTECODE_SIZE,
    MAX_INITCODE_SIZE,
    NON_RETURNING_SECTION,
)
from ethereum_test_tools.vm.opcode import Opcodes as Op

from .. import EOF_FORK_NAME
from .helpers import (
    default_address,
    simple_transaction,
    slot_code_should_fail,
    slot_code_worked,
    slot_create_address,
    slot_returndata,
    slot_returndata_size,
    smallest_initcode_subcontainer,
    smallest_runtime_subcontainer,
    value_canary_should_not_change,
    value_code_worked,
    value_create_failed,
)

REFERENCE_SPEC_GIT_PATH = "EIPS/eip-7620.md"
REFERENCE_SPEC_VERSION = "52ddbcdddcf72dd72427c319f2beddeb468e1737"

pytestmark = pytest.mark.valid_from(EOF_FORK_NAME)


@pytest.mark.parametrize(
    "revert",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"\x08\xc3\x79\xa0", id="Error(string)"),
    ],
)
def test_initcode_revert(state_test: StateTestFiller, revert: bytes):
    """
    Verifies proper handling of REVERT in initcode
    """
    env = Environment()
    revert_size = len(revert)

    initcode_subcontainer = Container(
        name="Initcode Subcontainer that reverts",
        sections=[
            Section.Code(
                code=Op.MSTORE(0, Op.PUSH32(revert)) + Op.REVERT(32 - revert_size, revert_size),
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=2,
            ),
        ],
    )

    factory_contract = Container(
        name="factory contract",
        sections=[
            Section.Code(
                code=Op.SSTORE(slot_create_address, Op.EOFCREATE[0](0, 0, 0, 0))
                + Op.SSTORE(slot_returndata_size, Op.RETURNDATASIZE)
                + Op.RETURNDATACOPY(Op.SUB(32, Op.RETURNDATASIZE), 0, Op.RETURNDATASIZE)
                + Op.SSTORE(slot_returndata, Op.MLOAD(0))
                + Op.SSTORE(slot_code_worked, value_code_worked)
                + Op.STOP,
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=4,
            ),
            Section.Container(container=initcode_subcontainer),
        ],
    )

    pre = {
        TestAddress: Account(balance=10**21, nonce=1),
        default_address: Account(code=factory_contract),
    }

    post = {
        default_address: Account(
            storage={
                slot_create_address: value_create_failed,
                slot_returndata_size: revert_size,
                slot_returndata: revert,
                slot_code_worked: value_code_worked,
            }
        )
    }

    state_test(env=env, pre=pre, post=post, tx=simple_transaction())


def test_initcode_aborts(
    state_test: StateTestFiller,
):
    """
    Verifies correct handling of a halt in EOF initcode
    """
    env = Environment()
    pre = {
        TestAddress: Account(balance=10**21, nonce=1),
        default_address: Account(
            code=Container(
                sections=[
                    Section.Code(
                        code=Op.SSTORE(slot_create_address, Op.EOFCREATE[0](0, 0, 0, 0))
                        + Op.SSTORE(slot_code_worked, value_code_worked)
                        + Op.STOP,
                        code_inputs=0,
                        code_outputs=NON_RETURNING_SECTION,
                        max_stack_height=4,
                    ),
                    Section.Container(
                        container=Container(
                            sections=[
                                Section.Code(
                                    code=Op.INVALID,
                                    code_inputs=0,
                                    code_outputs=NON_RETURNING_SECTION,
                                    max_stack_height=0,
                                )
                            ]
                        )
                    ),
                ]
            )
        ),
    }
    # Storage in slot_create_address should not have the address,
    post = {
        default_address: Account(
            storage={
                slot_create_address: value_create_failed,
                slot_code_worked: value_code_worked,
            }
        )
    }

    state_test(env=env, pre=pre, post=post, tx=simple_transaction())


"""
Size of the factory portion of test_eofcreate_deploy_sizes, but as the runtime code is dynamic, we
have to use a pre-calculated size
"""
factory_size = 30


@pytest.mark.parametrize(
    "target_deploy_size",
    [
        pytest.param(0x4000, id="large"),
        pytest.param(MAX_BYTECODE_SIZE, id="max"),
        pytest.param(MAX_BYTECODE_SIZE + 1, id="overmax"),
        pytest.param(MAX_INITCODE_SIZE - factory_size, id="initcodemax"),
        pytest.param(MAX_INITCODE_SIZE - factory_size + 1, id="initcodeovermax"),
        pytest.param(0xFFFF - factory_size, id="64k-1"),
    ],
)
def test_eofcreate_deploy_sizes(
    state_test: StateTestFiller,
    target_deploy_size: int,
):
    """
    Verifies a mix of runtime contract sizes mixing success and multiple size failure modes.
    """
    env = Environment()

    runtime_container = Container(
        sections=[
            Section.Code(
                code=Op.JUMPDEST * (target_deploy_size - len(smallest_runtime_subcontainer))
                + Op.STOP,
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=0,
            ),
        ]
    )

    initcode_subcontainer = Container(
        name="Initcode Subcontainer",
        sections=[
            Section.Code(
                code=Op.RETURNCONTRACT[0](0, 0),
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=2,
            ),
            Section.Container(container=runtime_container),
        ],
    )

    assert factory_size == (
        len(initcode_subcontainer) - len(runtime_container)
    ), "factory_size is wrong, expected factory_size is %d, calculated is %d" % (
        factory_size,
        len(initcode_subcontainer),
    )

    pre = {
        TestAddress: Account(balance=10**21, nonce=1),
        default_address: Account(
            code=Container(
                sections=[
                    Section.Code(
                        code=Op.SSTORE(slot_create_address, Op.EOFCREATE[0](0, 0, 0, 0))
                        + Op.SSTORE(slot_code_worked, value_code_worked)
                        + Op.STOP,
                        code_inputs=0,
                        code_outputs=NON_RETURNING_SECTION,
                        max_stack_height=4,
                    ),
                    Section.Container(container=initcode_subcontainer),
                ]
            )
        ),
    }
    # Storage in 0 should have the address,
    # Storage 1 is a canary of 1 to make sure it tried to execute, which also covers cases of
    #   data+code being greater than initcode_size_max, which is allowed.
    post = {
        default_address: Account(
            storage={
                slot_create_address: compute_eofcreate_address(
                    default_address, 0, initcode_subcontainer
                )
                if target_deploy_size <= MAX_BYTECODE_SIZE
                else value_create_failed,
                slot_code_worked: value_code_worked,
            }
        )
    }

    state_test(env=env, pre=pre, post=post, tx=simple_transaction())


@pytest.mark.parametrize(
    "auxdata_size",
    [
        pytest.param(MAX_BYTECODE_SIZE - len(smallest_runtime_subcontainer), id="maxcode"),
        pytest.param(MAX_BYTECODE_SIZE - len(smallest_runtime_subcontainer) + 1, id="overmaxcode"),
        pytest.param(0x10000 - 60, id="almost64k"),
        pytest.param(0x10000 - 1, id="64k-1"),
        pytest.param(0x10000, id="64k"),
        pytest.param(0x10000 + 1, id="over64k"),
    ],
)
def test_auxdata_size_failures(state_test: StateTestFiller, auxdata_size: int):
    """
    Exercises a number of auxdata size violations, and one maxcode success
    """
    env = Environment()
    auxdata_bytes = b"a" * auxdata_size

    initcode_subcontainer = Container(
        name="Initcode Subcontainer",
        sections=[
            Section.Code(
                code=Op.CALLDATACOPY(0, 0, Op.CALLDATASIZE)
                + Op.RETURNCONTRACT[0](0, Op.CALLDATASIZE),
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=3,
            ),
            Section.Container(container=smallest_runtime_subcontainer),
        ],
    )

    pre = {
        TestAddress: Account(balance=10**21, nonce=1),
        default_address: Account(
            code=Container(
                sections=[
                    Section.Code(
                        code=Op.CALLDATACOPY(0, 0, Op.CALLDATASIZE)
                        + Op.SSTORE(slot_create_address, Op.EOFCREATE[0](0, 0, 0, Op.CALLDATASIZE))
                        + Op.SSTORE(slot_code_worked, value_code_worked)
                        + Op.STOP,
                        code_inputs=0,
                        code_outputs=NON_RETURNING_SECTION,
                        max_stack_height=4,
                    ),
                    Section.Container(container=initcode_subcontainer),
                ]
            )
        ),
    }

    deployed_container_size = len(smallest_runtime_subcontainer) + auxdata_size

    # Storage in 0 will have address in first test, 0 in all other cases indicating failure
    # Storage 1 in 1 is a canary to see if EOFCREATE opcode halted
    post = {
        default_address: Account(
            storage={
                slot_create_address: compute_eofcreate_address(
                    default_address, 0, initcode_subcontainer
                )
                if deployed_container_size <= MAX_BYTECODE_SIZE
                else 0,
                slot_code_worked: value_code_worked,
            }
        )
    }

    state_test(env=env, pre=pre, post=post, tx=simple_transaction(payload=auxdata_bytes))


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(1, id="1_wei"),
        pytest.param(10**9, id="1_gwei"),
    ],
)
def test_eofcreate_insufficient_stipend(
    state_test: StateTestFiller,
    value: int,
):
    """
    Exercises an EOFCREATE that fails because the calling account does not have enough ether to
    pay the stipend
    """
    env = Environment()
    initcode_container = Container(
        sections=[
            Section.Code(
                code=Op.SSTORE(slot_create_address, Op.EOFCREATE[0](value, 0, 0, 0))
                + Op.SSTORE(slot_code_worked, value_code_worked)
                + Op.STOP,
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=4,
            ),
            Section.Container(container=smallest_initcode_subcontainer),
        ]
    )
    pre = {
        TestAddress: Account(balance=10**11, nonce=1),
        default_address: Account(balance=value - 1, code=initcode_container),
    }
    # create will fail but not trigger a halt, so canary at storage 1 should be set
    # also validate target created contract fails
    post = {
        default_address: Account(
            storage={
                slot_create_address: value_create_failed,
                slot_code_worked: value_code_worked,
            }
        ),
        compute_eofcreate_address(default_address, 0, initcode_container): Account.NONEXISTENT,
    }

    state_test(env=env, pre=pre, post=post, tx=simple_transaction())


def test_insufficient_initcode_gas(
    state_test: StateTestFiller,
):
    """
    Excercises an EOFCREATE when there is not enough gas for the initcode charge
    """
    env = Environment()

    initcode_data = b"a" * 0x5000
    initcode_container = Container(
        name="Large Initcode Subcontainer",
        sections=[
            Section.Code(
                code=Op.RETURNCONTRACT[0](0, 0),
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=2,
            ),
            Section.Container(container=smallest_runtime_subcontainer),
            Section.Data(data=initcode_data),
        ],
    )

    pre = {
        TestAddress: Account(balance=10**21, nonce=1),
        default_address: Account(
            code=Container(
                sections=[
                    Section.Code(
                        code=Op.SSTORE(slot_create_address, Op.EOFCREATE[0](0, 0, 0, 0))
                        + Op.SSTORE(slot_code_should_fail, value_code_worked)
                        + Op.STOP,
                        code_inputs=0,
                        code_outputs=NON_RETURNING_SECTION,
                        max_stack_height=4,
                    ),
                    Section.Container(container=initcode_container),
                ],
            ),
            storage={
                slot_create_address: value_canary_should_not_change,
                slot_code_should_fail: value_canary_should_not_change,
            },
        ),
    }
    # enough gas for everything but EVM opcodes and EIP-150 reserves
    gas_limit = 21_000 + 32_000 + (len(initcode_data) + 31) // 32 * 6
    # out_of_gas is triggered, so canary won't set value
    # also validate target created contract fails
    post = {
        default_address: Account(
            storage={
                slot_create_address: value_canary_should_not_change,
                slot_code_should_fail: value_canary_should_not_change,
            },
        ),
        compute_eofcreate_address(default_address, 0, initcode_container): Account.NONEXISTENT,
    }

    state_test(env=env, pre=pre, post=post, tx=simple_transaction(gas_limit=gas_limit))


def test_insufficient_gas_memory_expansion(
    state_test: StateTestFiller,
):
    """
    Excercises an EOFCREATE when the memory for auxdata has not been expanded but is requested
    """
    env = Environment()

    auxdata_size = 0x5000
    initcode_container = Container(
        sections=[
            Section.Code(
                code=Op.SSTORE(slot_create_address, Op.EOFCREATE[0](0, 0, 0, auxdata_size))
                + Op.SSTORE(slot_code_should_fail, slot_code_worked)
                + Op.STOP,
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=4,
            ),
            Section.Container(container=smallest_initcode_subcontainer),
        ],
    )
    pre = {
        TestAddress: Account(balance=10**21, nonce=1),
        default_address: Account(
            code=initcode_container,
            storage={
                slot_create_address: value_canary_should_not_change,
                slot_code_should_fail: value_canary_should_not_change,
            },
        ),
    }
    # enough gas for everything but EVM opcodes and EIP-150 reserves
    initcode_container_words = (len(initcode_container) + 31) // 32
    auxdata_size_words = (auxdata_size + 31) // 32
    gas_limit = (
        21_000
        + 32_000
        + initcode_container_words * 6
        + 3 * auxdata_size_words
        + auxdata_size_words * auxdata_size_words // 512
    )
    # out_of_gas is triggered, so canary won't set value
    # also validate target created contract fails
    post = {
        default_address: Account(
            storage={
                slot_create_address: value_canary_should_not_change,
                slot_code_should_fail: value_canary_should_not_change,
            },
        ),
        compute_eofcreate_address(default_address, 0, initcode_container): Account.NONEXISTENT,
    }

    state_test(env=env, pre=pre, post=post, tx=simple_transaction(gas_limit=gas_limit))


def test_insufficient_returncontract_auxdata_gas(
    state_test: StateTestFiller,
):
    """
    Excercises an EOFCREATE when there is not enough gas for the initcode charge
    """
    env = Environment()

    auxdata_size = 0x5000
    initcode_container = Container(
        name="Large Initcode Subcontainer",
        sections=[
            Section.Code(
                code=Op.RETURNCONTRACT[0](0, auxdata_size),
                code_inputs=0,
                code_outputs=NON_RETURNING_SECTION,
                max_stack_height=2,
            ),
            Section.Container(container=smallest_runtime_subcontainer),
        ],
    )

    pre = {
        TestAddress: Account(balance=10**21, nonce=1),
        default_address: Account(
            code=Container(
                sections=[
                    Section.Code(
                        code=Op.SSTORE(slot_create_address, Op.EOFCREATE[0](0, 0, 0, 0))
                        + Op.SSTORE(slot_code_should_fail, value_code_worked)
                        + Op.STOP,
                        code_inputs=0,
                        code_outputs=NON_RETURNING_SECTION,
                        max_stack_height=4,
                    ),
                    Section.Container(container=initcode_container),
                ],
            ),
            storage={
                slot_create_address: value_canary_should_not_change,
                slot_code_should_fail: value_canary_should_not_change,
            },
        ),
    }
    # enough gas for everything but EVM opcodes and EIP-150 reserves
    initcode_container_words = (len(initcode_container) + 31) // 32
    auxdata_size_words = (auxdata_size + 31) // 32
    gas_limit = (
        21_000
        + 32_000
        + initcode_container_words * 6
        + 3 * auxdata_size_words
        + auxdata_size_words * auxdata_size_words // 512
    )
    # out_of_gas is triggered, so canary won't set value
    # also validate target created contract fails
    post = {
        default_address: Account(
            storage={
                slot_create_address: value_canary_should_not_change,
                slot_code_should_fail: value_canary_should_not_change,
            },
        ),
        compute_eofcreate_address(default_address, 0, initcode_container): Account.NONEXISTENT,
    }

    state_test(env=env, pre=pre, post=post, tx=simple_transaction(gas_limit=gas_limit))
