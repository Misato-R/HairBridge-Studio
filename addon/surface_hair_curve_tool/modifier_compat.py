def _modifier_interface_inputs(modifier):
    if not modifier:
        return None
    try:
        inputs = modifier.properties.inputs
        inputs.keys()
    except (AttributeError, ReferenceError, TypeError):
        return None
    return inputs


def modifier_input_keys(modifier):
    inputs = _modifier_interface_inputs(modifier)
    if inputs is not None:
        try:
            return tuple(inputs.keys())
        except (ReferenceError, TypeError):
            return ()
    try:
        return tuple(modifier.keys())
    except (AttributeError, ReferenceError, TypeError):
        return ()


def modifier_input_ui_property(modifier, identifier):
    if not modifier or not identifier:
        return None
    inputs = _modifier_interface_inputs(modifier)
    if inputs is not None:
        try:
            socket = getattr(inputs, identifier)
            if socket.bl_rna.properties.get("value") is None:
                return None
        except (AttributeError, KeyError, ReferenceError, TypeError):
            return None
        return socket, "value"
    if identifier not in modifier_input_keys(modifier):
        return None
    return modifier, f'["{identifier}"]'


def modifier_input_value(modifier, identifier):
    if not modifier or not identifier:
        raise KeyError(identifier)
    inputs = _modifier_interface_inputs(modifier)
    if inputs is not None:
        try:
            socket = getattr(inputs, identifier)
            return socket.value
        except (AttributeError, KeyError, ReferenceError, TypeError) as exc:
            raise KeyError(identifier) from exc
    try:
        return modifier[identifier]
    except (KeyError, ReferenceError, TypeError) as exc:
        raise KeyError(identifier) from exc


def set_modifier_input_value(modifier, identifier, value):
    if not modifier or not identifier:
        return False
    inputs = _modifier_interface_inputs(modifier)
    if inputs is not None:
        try:
            socket = getattr(inputs, identifier)
            socket.value = value
        except (AttributeError, KeyError, ReferenceError, TypeError, ValueError):
            return False
        return True
    try:
        modifier[identifier] = value
    except (KeyError, ReferenceError, TypeError, ValueError):
        return False
    return True

