"""Permanent Telegram gateway orchestration over explicit durable state."""

import configparser
import math
import os
import signal
import time
from pathlib import Path

from survival import protocol, records, telegram_api


ACKNOWLEDGEMENT_MESSAGES = {
    "restart": "Restart accepted. I am staying online while the agent system restarts.",
    "reset": "Reset accepted. I am staying online while the agent system restarts.",
}
DEGRADED_REPLY = "I am degraded. I will reply properly after restart."


def acknowledgement(command):
    """Return the deterministic survival-command acknowledgement."""
    return ACKNOWLEDGEMENT_MESSAGES[command]


def command_record(accepted, command):
    """Project an immutable Task 1 update into the strict guardian protocol."""
    value = {
        "schema_version": 1,
        "request_id": accepted["id"],
        "telegram_update_id": accepted["telegram_update_id"],
        "telegram_user_id": accepted["telegram_user_id"],
        "command": command,
        "received_at": accepted["received_at"],
    }
    protocol.encode_command(value)
    return value


def handle_update(
    update,
    allowed,
    store,
    send,
    send_command,
    monotonic_now=time.monotonic,
    degraded_response_deadline_seconds=None,
):
    """Authenticate, durably accept, and idempotently dispatch one update."""
    projection = records._accepted_update(update)
    if projection["telegram_user_id"] not in allowed:
        telegram_api.store_denied_audit(store, update)
        return {"kind": "denied", "id": projection["id"]}

    accepted = records.accept_update(store, update, allowed)
    command = protocol.parse_literal_command(accepted["text"])
    if command is None:
        if degraded_response_deadline_seconds is None:
            timing = load_gateway_timing(_default_time_config_path())
            degraded_response_deadline_seconds = timing[
                "degraded_response_deadline_seconds"
            ]
        telegram_api.store_inbound(
            store,
            accepted,
            monotonic_now(),
            degraded_response_deadline_seconds,
        )
        return {"kind": "ordinary", "id": accepted["id"]}

    request = command_record(accepted, command)
    _deliver_guardian_command(store, request, send_command)
    _deliver_acknowledgement(
        store,
        accepted["id"],
        accepted["chat_id"],
        acknowledgement(command),
        send,
    )
    return {"kind": "command", "id": accepted["id"]}


def _deliver_guardian_command(store, request, send_command):
    path, state = telegram_api.ensure_command_delivery(store, request["request_id"])
    if state["egress_state"] == "delivered":
        return
    if state["egress_state"] == "sending":
        telegram_api.update_command_delivery_state(path, "delivery_unknown")
    telegram_api.update_command_delivery_state(path, "sending")
    try:
        send_command(request)
    except BaseException:
        telegram_api.update_command_delivery_state(path, "delivery_unknown")
        raise
    telegram_api.update_command_delivery_state(path, "delivered")


def _deliver_acknowledgement(store, request_id, chat_id, text, send):
    path, state = telegram_api.ensure_acknowledgement(
        store, request_id, chat_id, text,
    )
    if state["egress_state"] in {"delivered", "delivery_unknown"}:
        return state["egress_state"]
    if state["egress_state"] == "sending":
        telegram_api.update_acknowledgement_state(path, "delivery_unknown")
        return "delivery_unknown"
    return _perform_telegram_send(
        path,
        chat_id,
        text,
        send,
        telegram_api.update_acknowledgement_state,
    )


def send_due_degraded_responses(root, send, now):
    """Crash-truthfully send each exact inbox record whose deadline is due."""
    _require_number(now, "degraded response scan time")
    count = 0
    for path in telegram_api.list_inbox_entries(root):
        try:
            value = telegram_api.read_inbox_entry(path)
        except (OSError, ValueError) as error:
            telegram_api.quarantine_record(root, path, str(error))
            continue
        state = value["egress_state"]
        if state in {"delivered", "delivery_unknown"}:
            continue
        if state == "sending":
            telegram_api.update_inbox_state(path, "delivery_unknown")
            count += 1
            continue
        if now < value["deadline_at"]:
            continue
        _perform_telegram_send(
            path,
            value["chat_id"],
            DEGRADED_REPLY,
            send,
            telegram_api.update_inbox_state,
        )
        count += 1
    return count


def drain_critical_outbox(store, send):
    """Crash-truthfully deliver exact critical Telegram egress records."""
    count = 0
    for path in telegram_api.list_critical_outbox(store):
        try:
            value = telegram_api.read_critical_outbox_entry(path)
        except (OSError, ValueError) as error:
            telegram_api.quarantine_record(store, path, str(error))
            continue
        state = value["egress_state"]
        if state in {"delivered", "delivery_unknown"}:
            continue
        if state == "sending":
            telegram_api.update_critical_outbox_state(path, "delivery_unknown")
            count += 1
            continue
        _perform_telegram_send(
            path,
            value["chat_id"],
            value["text"],
            send,
            telegram_api.update_critical_outbox_state,
        )
        count += 1
    return count


def _perform_telegram_send(path, chat_id, text, send, update_state):
    update_state(path, "sending")
    try:
        result = send(chat_id, text)
    except BaseException:
        update_state(path, "delivery_unknown")
        raise
    state = "delivery_unknown" if result is False else "delivered"
    update_state(path, state)
    return state


def check_quarantine_health(store):
    """Report whether durable corruption evidence is absent."""
    return telegram_api.quarantine_is_empty(store)


def gateway_is_healthy(store, monotonic_now, maximum_age_seconds):
    """Require fresh poll and egress observations plus an empty quarantine."""
    _require_number(monotonic_now, "gateway health observation time")
    _require_positive_number(maximum_age_seconds, "gateway heartbeat maximum age")
    if not check_quarantine_health(store):
        return False
    try:
        heartbeats = {
            worker: telegram_api.read_worker_heartbeat(store, worker)
            for worker in ("poll", "egress")
        }
    except (OSError, ValueError):
        return False
    for value in heartbeats.values():
        observed_at = value["monotonic_at"]
        if observed_at > monotonic_now or monotonic_now - observed_at > maximum_age_seconds:
            return False
    return True


def mark_gateway_heartbeat(store, monotonic_now, maximum_age_seconds=None):
    """Renew overall health only when both worker observations are fresh."""
    if maximum_age_seconds is None:
        maximum_age_seconds = load_gateway_timing(_default_time_config_path())[
            "heartbeat_maximum_age_seconds"
        ]
    if not gateway_is_healthy(store, monotonic_now, maximum_age_seconds):
        return
    poll = telegram_api.read_worker_heartbeat(store, "poll")
    egress = telegram_api.read_worker_heartbeat(store, "egress")
    telegram_api.write_gateway_heartbeat(
        store,
        poll["monotonic_at"],
        egress["monotonic_at"],
        monotonic_now,
    )


def mark_worker_heartbeat(store, worker, monotonic_now, maximum_age_seconds):
    """Record one worker observation and conditionally renew overall health."""
    telegram_api.write_worker_heartbeat(store, worker, monotonic_now)
    mark_gateway_heartbeat(store, monotonic_now, maximum_age_seconds)


def poll_child(
    store,
    allowed,
    send,
    send_command,
    *,
    degraded_response_deadline_seconds,
    poll_seconds,
    long_poll_seconds,
    request_timeout_seconds,
    heartbeat_maximum_age_seconds,
    get_updates,
    monotonic_now=time.monotonic,
    sleep=time.sleep,
    maximum_iterations=None,
):
    """Long-poll and dispatch; any poll or dispatch failure exits this worker."""
    offset = None
    iterations = 0
    while maximum_iterations is None or iterations < maximum_iterations:
        updates = get_updates(
            offset=offset,
            timeout=long_poll_seconds,
            request_timeout=request_timeout_seconds,
        )
        if type(updates) is not list:
            raise RuntimeError("invalid Telegram update batch")
        for update in updates:
            handle_update(
                update,
                allowed,
                store,
                send,
                send_command,
                monotonic_now=monotonic_now,
                degraded_response_deadline_seconds=degraded_response_deadline_seconds,
            )
            update_id = update.get("update_id")
            if type(update_id) is not int or update_id < 0:
                raise ValueError("invalid Telegram update identity")
            offset = update_id + 1
        now = monotonic_now()
        mark_worker_heartbeat(store, "poll", now, heartbeat_maximum_age_seconds)
        iterations += 1
        if maximum_iterations is None or iterations < maximum_iterations:
            sleep(poll_seconds)


def egress_child(
    store,
    send,
    *,
    outbox_poll_seconds,
    heartbeat_maximum_age_seconds,
    monotonic_now=time.monotonic,
    sleep=time.sleep,
    maximum_iterations=None,
):
    """Drain Telegram egress and renew only its own successful-loop heartbeat."""
    iterations = 0
    while maximum_iterations is None or iterations < maximum_iterations:
        drain_critical_outbox(store, send)
        now = monotonic_now()
        send_due_degraded_responses(store, send, now)
        if check_quarantine_health(store):
            mark_worker_heartbeat(store, "egress", now, heartbeat_maximum_age_seconds)
        iterations += 1
        if maximum_iterations is None or iterations < maximum_iterations:
            sleep(outbox_poll_seconds)


def main(
    store,
    allowed,
    send,
    send_command,
    *,
    degraded_response_deadline_seconds,
    poll_seconds,
    long_poll_seconds,
    request_timeout_seconds,
    outbox_poll_seconds,
    heartbeat_maximum_age_seconds,
    get_updates=telegram_api.get_updates,
    fork=os.fork,
    waitpid=os.waitpid,
    child_exit=os._exit,
    install_signal_handlers=None,
):
    """Supervise two tracked workers using exactly one wait result per loop."""
    store.mkdir(parents=True, exist_ok=True)
    if install_signal_handlers is None:
        install_signal_handlers = _install_signal_handlers
    install_signal_handlers()

    worker_arguments = {
        "poll": lambda: poll_child(
            store,
            allowed,
            send,
            send_command,
            degraded_response_deadline_seconds=degraded_response_deadline_seconds,
            poll_seconds=poll_seconds,
            long_poll_seconds=long_poll_seconds,
            request_timeout_seconds=request_timeout_seconds,
            heartbeat_maximum_age_seconds=heartbeat_maximum_age_seconds,
            get_updates=get_updates,
        ),
        "egress": lambda: egress_child(
            store,
            send,
            outbox_poll_seconds=outbox_poll_seconds,
            heartbeat_maximum_age_seconds=heartbeat_maximum_age_seconds,
        ),
    }

    def spawn(worker):
        pid = fork()
        if pid == 0:
            worker_arguments[worker]()
            child_exit(0)
        return pid

    children = {"poll": spawn("poll"), "egress": spawn("egress")}
    while True:
        try:
            dead_pid, _status = waitpid(-1, 0)
        except ChildProcessError:
            return dict(children)
        for worker, pid in children.items():
            if pid == dead_pid:
                children[worker] = spawn(worker)
                break


def _install_signal_handlers():
    def terminate_group(_signum, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.killpg(os.getpgrp(), signal.SIGTERM)

    signal.signal(signal.SIGTERM, terminate_group)


def load_gateway_timing(path):
    """Parse the exact gateway timing projection from central policy."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with Path(path).open(encoding="utf-8") as source:
            parser.read_file(source)
    except (OSError, configparser.Error) as error:
        raise RuntimeError(f"cannot parse gateway timing configuration: {path}") from error
    names = {
        "poll_seconds": ("telegram", "poll_seconds"),
        "long_poll_seconds": ("telegram", "long_poll_seconds"),
        "request_timeout_seconds": ("telegram", "request_timeout_seconds"),
        "command_acknowledgement_deadline_seconds": (
            "telegram", "command_acknowledgement_deadline_seconds",
        ),
        "degraded_response_deadline_seconds": (
            "telegram", "degraded_response_deadline_seconds",
        ),
        "heartbeat_maximum_age_seconds": ("heartbeat", "maximum_age_seconds"),
        "outbox_poll_seconds": ("outbox", "poll_seconds"),
    }
    values = {}
    for name, (section, option) in names.items():
        try:
            value = parser.getfloat(section, option)
        except (configparser.Error, ValueError) as error:
            raise RuntimeError(f"invalid timing key {section}.{option}") from error
        if not math.isfinite(value) or value <= 0:
            raise RuntimeError(f"invalid timing key {section}.{option}")
        values[name] = value
    return values


def load_production_config(environ=None):
    """Load every production identity, path, secret, and timing without defaults."""
    if environ is None:
        environ = os.environ
    credentials_directory = _required_environment(environ, "CREDENTIALS_DIRECTORY")
    allowed_path = _required_environment(environ, "GUARDIAN_ALLOWED_USER_IDS_PATH")
    store_path = _required_environment(environ, "SURVIVAL_STORE_DIR")
    guardian_socket_path = _required_environment(environ, "GUARDIAN_SOCKET_PATH")
    time_config_path = _required_environment(environ, "TIME_CONFIG_PATH")
    timing = load_gateway_timing(time_config_path)
    return {
        "bot_token": telegram_api.read_bot_token(credentials_directory),
        "allowed_users": telegram_api.read_allowed_user_ids(allowed_path),
        "store_path": Path(store_path),
        "guardian_socket_path": guardian_socket_path,
        **timing,
    }


def run_production(
    environ=None,
    *,
    send_message=telegram_api.send_message,
    submit_to_guardian=telegram_api.submit_to_guardian,
    get_updates_api=telegram_api.get_updates,
    run_main=main,
):
    """Construct literal transport adapters only after complete config validation."""
    config = load_production_config(environ)

    def send(chat_id, text):
        return send_message(
            config["bot_token"],
            chat_id,
            text,
            request_timeout=config["request_timeout_seconds"],
        )

    def send_command(command):
        return submit_to_guardian(
            config["guardian_socket_path"],
            command,
            timeout=config["command_acknowledgement_deadline_seconds"],
        )

    def get_updates(**arguments):
        return get_updates_api(config["bot_token"], **arguments)

    return run_main(
        config["store_path"],
        config["allowed_users"],
        send,
        send_command,
        degraded_response_deadline_seconds=config[
            "degraded_response_deadline_seconds"
        ],
        poll_seconds=config["poll_seconds"],
        long_poll_seconds=config["long_poll_seconds"],
        request_timeout_seconds=config["request_timeout_seconds"],
        outbox_poll_seconds=config["outbox_poll_seconds"],
        heartbeat_maximum_age_seconds=config["heartbeat_maximum_age_seconds"],
        get_updates=get_updates,
    )


def _required_environment(environ, name):
    value = environ.get(name)
    if type(value) is not str or not value:
        raise RuntimeError(f"missing {name}")
    return value


def _default_time_config_path():
    configured = os.environ.get("TIME_CONFIG_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "config" / "time.cfg"


def _require_number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"invalid {name}")


def _require_positive_number(value, name):
    _require_number(value, name)
    if value <= 0:
        raise ValueError(f"invalid {name}")


if __name__ == "__main__":
    run_production()
