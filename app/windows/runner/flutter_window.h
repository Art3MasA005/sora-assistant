#ifndef RUNNER_FLUTTER_WINDOW_H_
#define RUNNER_FLUTTER_WINDOW_H_

#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>

#include <memory>

#include "win32_window.h"

// "End now" for a running Sora (sent by `sora.exe --quit`, which the uninstaller runs): unlike
// closing the window, which only hides it to the notification area.
inline UINT SoraQuitMessage() {
  static const UINT message = ::RegisterWindowMessageW(L"SoraQuit");
  return message;
}

// A window that does nothing but host a Flutter view.
class FlutterWindow : public Win32Window {
 public:
  // Creates a new FlutterWindow hosting a Flutter view running |project|, shown once its first frame is
  // drawn. |activate|: and brought to the front (the corner orb is shown without taking the focus).
  explicit FlutterWindow(const flutter::DartProject& project, bool activate = true);
  virtual ~FlutterWindow();

 protected:
  // Win32Window:
  bool OnCreate() override;
  void OnDestroy() override;
  LRESULT MessageHandler(HWND window, UINT const message, WPARAM const wparam,
                         LPARAM const lparam) noexcept override;

 private:
  // The project to run.
  flutter::DartProject project_;

  bool activate_;

  // The corner orb's watch on the foreground window (see OnForeground in the .cpp).
  HWINEVENTHOOK foreground_hook_ = nullptr;

 public:
  static HWND last_foreground_;

 private:

  // The Flutter instance hosted by this window.
  std::unique_ptr<flutter::FlutterViewController> flutter_controller_;
};

#endif  // RUNNER_FLUTTER_WINDOW_H_
