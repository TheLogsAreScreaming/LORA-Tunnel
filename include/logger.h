#pragma once
#include "app_types.h"
namespace tunnel {
// Numeric breadcrumbs only: no session IDs, paths, packet contents or keys.
enum class LoggerFailureReason : uint32_t {
  None=0, Mount=1, MissingCard=2, SessionsDirectory=3, SessionOpen=4,
  BatchWrite=5, BatchFlush=6, SessionClose=7
};
struct LoggerDiagnostics {
  uint32_t failures=0,reason=0,operation=0;
  int32_t error=0;
};
// First failure is retained until reboot, including across close/remount/new
// sessions. failures saturates at UINT32_MAX; reading does not reset anything.
// operation is numeric storage::Failure; error is CheckedFile's retained errno.
// Mount/card/directory APIs lack reliable errno and report operation/error=0.
LoggerDiagnostics loggerDiagnostics();
bool mountStorage();
bool storageReady();
uint32_t loggerStackMargin();
// Returns false if the board-profile queue or writer task cannot be allocated.
bool loggerBegin();
bool logObservation(const Observation& observation);
bool loggerIdle();
// Cardputer upload maintenance reuses the existing writer stack. The request
// must be made while capture and the writer are idle. One pending callback is
// allowed; it runs on writer core 0 without busMutex, outside all file work.
// complete runs after maintenance ownership is released. No heap is allocated.
bool loggerRequestMaintenance(void (*run)(void*),void* context,void (*complete)());
// True only inside that writer-owned callback with no session/queue/file work.
// BLE transitions use this instead of exposing a false idle state to callers.
bool loggerMaintenanceQuiescent();
// Caller owns busMutex. Refuses an active or queued session.
bool unmountStorageForSleep();
}
