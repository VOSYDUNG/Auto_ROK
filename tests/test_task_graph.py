from harness.task_graph import FlowRegistry, TaskFlow, Transition


def _switch_character_flow() -> TaskFlow:
    return TaskFlow(
        flow_id="SWITCH_CHARACTER",
        transitions=(
            Transition(
                from_state="ACCOUNT_CHARACTER_LIST",
                action_id="SELECT_DIFFERENT_CHARACTER",
                expect_states=("CHARACTER_LOGIN_CONFIRM",),
                requires_target=True,
                target_ids=("CHARACTER_CARD",),
            ),
            Transition(
                from_state="CHARACTER_LOGIN_CONFIRM",
                action_id="CONFIRM_CHARACTER_LOGIN",
                expect_family="MAIN_GAME_VIEW",
                requires_target=True,
                target_ids=("CHARACTER_LOGIN_YES",),
                completion_edge=True,
            ),
        ),
        completion_families=("MAIN_GAME_VIEW",),
    )


def test_outgoing_edges_compile_to_allowed_actions():
    flow = _switch_character_flow()

    actions = flow.allowed_actions("ACCOUNT_CHARACTER_LIST")

    assert len(actions) == 1
    assert actions[0].action_id == "SELECT_DIFFERENT_CHARACTER"
    assert actions[0].requires_target is True
    assert actions[0].target_ids == ("CHARACTER_CARD",)


def test_unknown_action_is_not_part_of_current_surface():
    flow = _switch_character_flow()

    assert flow.transition_for("ACCOUNT_CHARACTER_LIST", "CONFIRM_CHARACTER_LOGIN") is None


def test_async_login_accepts_main_game_state_family_without_identity_ocr():
    flow = _switch_character_flow()
    edge = flow.transition_for("CHARACTER_LOGIN_CONFIRM", "CONFIRM_CHARACTER_LOGIN")

    assert edge is not None
    assert flow.accepts_observation(
        edge,
        observed_state="CITY_VIEW",
        observed_family="MAIN_GAME_VIEW",
    )
    assert flow.is_complete("CITY_VIEW", family="MAIN_GAME_VIEW")


def test_registry_rejects_duplicate_flow_ids():
    flow = _switch_character_flow()

    try:
        FlowRegistry((flow, flow))
    except ValueError as exc:
        assert "duplicate flow_id" in str(exc)
    else:
        raise AssertionError("expected duplicate flow ids to be rejected")
