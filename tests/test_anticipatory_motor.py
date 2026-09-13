from harness.anticipatory_motor import (
    AnticipatoryMotorController,
    MotorMode,
    MotorPrior,
    ScreenProfile,
)


class FakePointer:
    def __init__(self) -> None:
        self.moves = []
        self.clicks = []

    def move_to(self, x: int, y: int) -> None:
        self.moves.append((x, y))

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


def test_preposition_moves_without_clicking():
    pointer = FakePointer()
    controller = AnticipatoryMotorController(pointer)
    profile = ScreenProfile("1080p", 1920, 1080)
    prior = MotorPrior(
        prior_id="claim-next",
        from_state="ALLIANCE_HOME",
        expected_next_state="ALLIANCE_TERRITORY",
        action_id="CLAIM_ALLIANCE_TERRITORY_RSS",
        normalized_x=0.70,
        normalized_y=0.25,
        mode=MotorMode.PREPOSITION,
        profile_id="1080p",
        confidence=0.98,
    )

    result = controller.stage(prior, profile)

    assert result.click_sent is False
    assert pointer.moves == [(1344, 270)]
    assert pointer.clicks == []


def test_optimistic_actuation_clicks_stable_prior():
    pointer = FakePointer()
    controller = AnticipatoryMotorController(pointer)
    profile = ScreenProfile("1080p", 1920, 1080)
    prior = MotorPrior(
        prior_id="yes-login",
        from_state="ACCOUNT_CHARACTER_LIST",
        expected_next_state="CHARACTER_LOGIN_CONFIRM",
        action_id="CONFIRM_CHARACTER_LOGIN",
        normalized_x=0.60,
        normalized_y=0.66,
        mode=MotorMode.OPTIMISTIC_ACTUATE,
        profile_id="1080p",
        confidence=0.99,
        stable_layout=True,
    )

    result = controller.stage(prior, profile)

    assert result.click_sent is True
    assert pointer.moves == [(1152, 713)]
    assert pointer.clicks == [(1152, 713)]


def test_profile_mismatch_rejects_prior():
    pointer = FakePointer()
    controller = AnticipatoryMotorController(pointer)
    profile = ScreenProfile("1440p", 2560, 1440)
    prior = MotorPrior(
        prior_id="yes-login",
        from_state="ACCOUNT_CHARACTER_LIST",
        expected_next_state="CHARACTER_LOGIN_CONFIRM",
        action_id="CONFIRM_CHARACTER_LOGIN",
        normalized_x=0.60,
        normalized_y=0.66,
        mode=MotorMode.PREPOSITION,
        profile_id="1080p",
        confidence=0.99,
    )

    try:
        controller.stage(prior, profile)
        assert False, "expected profile mismatch"
    except ValueError as exc:
        assert "belongs to profile" in str(exc)
