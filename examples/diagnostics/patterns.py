"""Authored inspection fixture. Its functions are never run by the inspector."""


def collect(value, history=[]):
    history.append(value)
    return history


def select_route(load):
    if load > 0.5:
        local = True
    else:
        local = False
    return local


def retry(operation):
    while True:
        try:
            operation()
        except Exception:
            continue
