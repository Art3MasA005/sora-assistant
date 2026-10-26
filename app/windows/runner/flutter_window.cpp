#include "flutter_window.h"

#include <optional>

#include "flutter/generated_plugin_registrant.h"

HWND FlutterWindow::last_foreground_ = nullptr;

// The corner orb hands the focus back to the window that had it (posted, see WM_ACTIVATE).
static constexpr UINT kGiveFocusBack = WM_APP + 0x51;

// The corner orb: which other window has the focus, so the orb can hand it back if it ever gets it.
static void CALLBACK OnForeground(HWINEVENTHOOK, DWORD, HWND hwnd, LONG, LONG, DWORD, DWORD) {
  if (hwnd != nullptr) FlutterWindow::last_foreground_ = hwnd;
}

FlutterWindow::FlutterWindow(const flutter::DartProject& project, bool activate)
    : project_(project), activate_(activate) {}

FlutterWindow::~FlutterWindow() {}

bool FlutterWindow::OnCreate() {
  if (!Win32Window::OnCreate()) {
    return false;
  }

  RECT frame = GetClientArea();

  // The size here must match the window dimensions to avoid unnecessary surface
  // creation / destruction in the startup path.
  flutter_controller_ = std::make_unique<flutter::FlutterViewController>(
      frame.right - frame.left, frame.bottom - frame.top, project_);
  // Ensure that basic setup of the controller was successful.
  if (!flutter_controller_->engine() || !flutter_controller_->view()) {
    return false;
  }
  RegisterPlugins(flutter_controller_->engine());
  SetChildContent(flutter_controller_->view()->GetNativeWindow());

  if (!activate_) {
    // Told by Windows when the foreground window changes (other processes only): no polling. (Where the
    // focus was before is noted in main.cpp, before this window existed: it is this window's by now.)
    foreground_hook_ = ::SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, nullptr, OnForeground, 0, 0,
                                         WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS);
  }

  flutter_controller_->engine()->SetNextFrameCallback([&]() {
    if (activate_) {
      this->Show();
    } else {
      ::ShowWindow(GetHandle(), SW_SHOWNOACTIVATE);
    }
  });

  // Flutter can complete the first frame before the "show window" callback is
  // registered. The following call ensures a frame is pending to ensure the
  // window is shown. It is a no-op if the first frame hasn't completed yet.
  flutter_controller_->ForceRedraw();

  return true;
}

void FlutterWindow::OnDestroy() {
  if (foreground_hook_ != nullptr) {
    ::UnhookWinEvent(foreground_hook_);
    foreground_hook_ = nullptr;
  }
  if (flutter_controller_) {
    flutter_controller_ = nullptr;
  }

  Win32Window::OnDestroy();
}

LRESULT
FlutterWindow::MessageHandler(HWND hwnd, UINT const message,
                              WPARAM const wparam,
                              LPARAM const lparam) noexcept {
  // Asked to end for real: by `sora.exe --quit` (the uninstaller), or by Windows closing apps for an
  // installer's update, a sign-out or a shutdown. Closing would only hide the window to the tray, so
  // the window is destroyed instead; that also takes the tray icon away (the tray plugin removes it
  // on WM_DESTROY) and ends the app (quit on close).
  if (message == SoraQuitMessage() || (message == WM_ENDSESSION && wparam)) {
    ::DestroyWindow(hwnd);
    return 0;
  }

  // The corner orb never takes the focus from what the owner is doing: no move or resize activates it
  // (window_manager's SetWindowPos calls would), no click does, and if something activates it anyway
  // the focus goes straight back to the window that had it.
  if (!activate_) {
    switch (message) {
      case WM_WINDOWPOSCHANGING:
        reinterpret_cast<WINDOWPOS*>(lparam)->flags |= SWP_NOACTIVATE;
        break;
      case WM_MOUSEACTIVATE:
        return MA_NOACTIVATE;
      case WM_ACTIVATE:
        // (Flutter's view takes the keyboard focus when it is first shown, which activates this window.)
        // Handed back once the activation is over: during it, SetForegroundWindow is ignored. lparam
        // names the window that lost the focus only when it is this thread's; else the foreground hook's.
        if (LOWORD(wparam) != WA_INACTIVE) {
          HWND back = lparam != 0 ? reinterpret_cast<HWND>(lparam) : last_foreground_;
          if (back != nullptr && back != hwnd) ::PostMessageW(hwnd, kGiveFocusBack, 0, reinterpret_cast<LPARAM>(back));
        }
        break;
      case kGiveFocusBack:
        if (::IsWindow(reinterpret_cast<HWND>(lparam))) ::SetForegroundWindow(reinterpret_cast<HWND>(lparam));
        return 0;
    }
  }

  // Give Flutter, including plugins, an opportunity to handle window messages.
  if (flutter_controller_) {
    std::optional<LRESULT> result =
        flutter_controller_->HandleTopLevelWindowProc(hwnd, message, wparam,
                                                      lparam);
    if (result) {
      return *result;
    }
  }

  switch (message) {
    case WM_FONTCHANGE:
      flutter_controller_->engine()->ReloadSystemFonts();
      break;
  }

  return Win32Window::MessageHandler(hwnd, message, wparam, lparam);
}
