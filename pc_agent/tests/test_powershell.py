import windows_actions as w


def test_values_travel_in_the_environment_not_the_command(monkeypatch):
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, b"ok", b""

    def run(args, timeout=30, input_bytes=None, env=None):
        seen.update(args=args, env=env)
        return Done()

    monkeypatch.setattr(w, "_run", run)
    evil = 'notepad" ; $(Start-Process calc) ; "'
    assert w._powershell("param($name, $force) $name", evil, "1") == "ok"
    command = " ".join(seen["args"])
    assert "calc" not in command and evil not in command  # never part of the code PowerShell parses
    assert seen["env"]["SORA_ARG0"] == evil and seen["env"]["SORA_ARG1"] == "1"
    assert "$sora_args = @($env:SORA_ARG0,$env:SORA_ARG1); & {param($name, $force) $name} @sora_args" in command

    w._powershell("Get-Date")
    assert seen["args"][-1].endswith("$sora_args = @(); & {Get-Date} @sora_args")
