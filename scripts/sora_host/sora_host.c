// Sora.exe: the project's Python, under Sora's name and icon.
//
// Windows names a program after its .exe's version info, so the server and the PC agent run with
// pythonw.exe showed up as "Python" (microphone privacy list, Task Manager). This host lives in
// .venv\Scripts, loads the Python DLL from the venv's base install (pyvenv.cfg `home`) and runs
// Py_Main in its own process, so they show up as "Sora". Built by build.ps1 next to this file.

#define WIN32_LEAN_AND_MEAN
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#ifndef PY_DLL
#define PY_DLL L"python3.dll"
#endif

typedef int(__cdecl *PyMainFn)(int, wchar_t **);

static int fail(const wchar_t *message) {
    MessageBoxW(NULL, message, L"Sora", MB_ICONERROR);
    return 1;
}

// `home = C:\...\Python314` from <venv>\pyvenv.cfg (this exe is <venv>\Scripts\Sora.exe).
static int read_home(wchar_t *home, size_t size) {
    wchar_t cfg[MAX_PATH];
    if (!GetModuleFileNameW(NULL, cfg, MAX_PATH)) return 0;
    for (int i = 0; i < 2; i++) {
        wchar_t *slash = wcsrchr(cfg, L'\\');
        if (slash) *slash = 0;
    }
    if (wcscat_s(cfg, MAX_PATH, L"\\pyvenv.cfg")) return 0;
    FILE *f = NULL;
    if (_wfopen_s(&f, cfg, L"rb") || !f) return 0;
    char line[1024];
    int found = 0;
    while (!found && fgets(line, sizeof line, f)) {
        char *eq = strchr(line, '=');
        if (!eq) continue;
        char *key = line, *end = eq;
        while (end > key && (end[-1] == ' ' || end[-1] == '\t')) end--;
        if (end - key != 4 || _strnicmp(key, "home", 4)) continue;
        char *value = eq + 1;
        while (*value == ' ' || *value == '\t') value++;
        value[strcspn(value, "\r\n")] = 0;
        found = MultiByteToWideChar(CP_UTF8, 0, value, -1, home, (int)size) > 0;
    }
    fclose(f);
    return found;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show) {
    (void)instance, (void)previous, (void)command_line, (void)show;
    wchar_t home[MAX_PATH], dll[MAX_PATH];
    if (!read_home(home, MAX_PATH)) return fail(L"Can't read pyvenv.cfg next to the Scripts folder.");
    if (swprintf_s(dll, MAX_PATH, L"%ls\\%ls", home, PY_DLL) < 0) return 1;
    // The DLL's own folder is searched for its dependencies (vcruntime140.dll).
    HMODULE python = LoadLibraryExW(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!python) return fail(L"Can't load the Python DLL (was Python updated? Run scripts\\sora_host\\build.ps1 again).");
    PyMainFn py_main = (PyMainFn)GetProcAddress(python, "Py_Main");
    if (!py_main) return fail(L"Py_Main not found in the Python DLL.");
    return py_main(__argc, __wargv);
}
