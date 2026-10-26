#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>
#include <windows.h>

#include "flutter_window.h"
#include "utils.h"

// Asks the running Sora window titled |title| to end (SoraQuitMessage) and waits for it, up to 10 s.
static void EndRunning(const wchar_t* title) {
  HWND existing = ::FindWindowW(L"FLUTTER_RUNNER_WIN32_WINDOW", title);
  if (existing == nullptr) return;
  DWORD pid = 0;
  ::GetWindowThreadProcessId(existing, &pid);
  HANDLE running = ::OpenProcess(SYNCHRONIZE, FALSE, pid);
  ::PostMessageW(existing, SoraQuitMessage(), 0, 0);
  if (running != nullptr) {
    ::WaitForSingleObject(running, 10000);
    ::CloseHandle(running);
  }
}

int APIENTRY wWinMain(_In_ HINSTANCE instance, _In_opt_ HINSTANCE prev,
                      _In_ wchar_t *command_line, _In_ int show_command) {
  // `sora.exe --quit` (the uninstaller): end the running Sora, tray icon and all, and wait for it.
  const bool quit = command_line != nullptr && ::wcsstr(command_line, L"--quit") != nullptr;
  // `sora.exe --orb --port N --token T`: the PC agent's corner orb for "Hey Sora" (lib/desktop/orb_overlay.dart).
  // Its own small hidden window, beside the app (not the one Sora app, so no single-instance check).
  const bool orb = command_line != nullptr && ::wcsstr(command_line, L"--orb") != nullptr;

  if (quit) {
    EndRunning(L"Sora");
    EndRunning(L"Sora orb");  // the PC agent's corner orb runs this exe too
    return EXIT_SUCCESS;
  }

  // One Sora app: opened again while it runs (perhaps hidden in the notification area after the
  // window was closed), it brings that window back instead of starting a second copy.
  if (!orb) ::CreateMutexW(nullptr, FALSE, L"Local\\sora-app");
  if (!orb && ::GetLastError() == ERROR_ALREADY_EXISTS) {
    HWND existing = ::FindWindowW(L"FLUTTER_RUNNER_WIN32_WINDOW", L"Sora");
    if (existing != nullptr) {
      ::ShowWindow(existing, ::IsIconic(existing) ? SW_RESTORE : SW_SHOW);
      ::SetForegroundWindow(existing);
    }
    return EXIT_SUCCESS;
  }

  // Attach to console when present (e.g., 'flutter run') or create a
  // new console when running with a debugger.
  if (!::AttachConsole(ATTACH_PARENT_PROCESS) && ::IsDebuggerPresent()) {
    CreateAndAttachConsole();
  }

  // Initialize COM, so that it is available for use in the library and/or
  // plugins.
  ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

  flutter::DartProject project(L"data");

  std::vector<std::string> command_line_arguments =
      GetCommandLineArguments();

  project.set_dart_entrypoint_arguments(std::move(command_line_arguments));

  if (orb) {
    // Where the focus is now: Flutter's view takes the keyboard focus while the window is being made,
    // which activates it, and the orb hands the focus straight back (FlutterWindow, WM_ACTIVATE).
    FlutterWindow::last_foreground_ = ::GetForegroundWindow();
  }
  FlutterWindow window(project, !orb);
  Win32Window::Point origin(10, 10);
  Win32Window::Size size = orb ? Win32Window::Size(180, 180) : Win32Window::Size(1280, 720);
  if (!window.Create(orb ? L"Sora orb" : L"Sora", origin, size)) {
    return EXIT_FAILURE;
  }
  if (orb) {
    HWND hwnd = window.GetHandle();
    // A process's first ShowWindow may follow how it was started (and activate it) whatever it asks:
    // spend it on hiding, so showing later obeys SW_SHOWNOACTIVATE.
    ::ShowWindow(hwnd, SW_HIDE);
    // Never takes the focus from what the owner is doing, isn't on the taskbar or in Alt+Tab, and
    // clicks go through it to the window below (layered + transparent, drawn at full opacity).
    ::SetWindowLongW(hwnd, GWL_EXSTYLE,
                     ::GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_TRANSPARENT);
    ::SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA);
    ::SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
  }
  window.SetQuitOnClose(true);

  ::MSG msg;
  while (::GetMessage(&msg, nullptr, 0, 0)) {
    ::TranslateMessage(&msg);
    ::DispatchMessage(&msg);
  }

  ::CoUninitialize();
  return EXIT_SUCCESS;
}
