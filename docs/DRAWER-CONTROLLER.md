# ESP32 XY drawer controller

Partshelf supports drawer organizers with 1–16 columns, 1–16 rows per section, and 1–8 vertically stacked sections, up to 512 drawers. Existing organizers retain their original 8×16 layout. A single ESP32 controls the shared XY carriage, servo, and LED. Firmware is separate: this document is the HTTP contract to implement on the ESP32. No GPIO or stepper-driver assumptions are made by the website.

## Website setup

1. Open **Storage areas → Add drawer organizer**. Set columns, rows per section, stacked sections, and an organizer color. The default 8 columns × 8 rows × 2 sections creates 128 ordinary storage locations (A1–P8). The existing component create/edit form can use them too.
2. Reserve a LAN IP address for the ESP32. The Partshelf LXC must be able to reach it. The browser does not contact the ESP32 directly; HTTPS users outside your home use the same website controls.
3. Authorize the controller for the workspace in `/etc/partshelf.env` (on this installation it points into `/mnt/partshelf/config`). The cabinet page displays the workspace ID. Example, for workspace 1:

   ```ini
   PARTSHELF_DEVICE_ENDPOINTS='{"1":["http://192.168.1.50"]}'
   ```

   Then restart `partshelf` with `systemctl restart partshelf`. This operator-controlled mapping prevents public accounts from sending requests to arbitrary addresses on your server's LAN. Give a controller to only one workspace. Do not expose its port to the internet. HTTP carries its device key over the trusted LAN; HTTPS endpoints are also supported with normal certificate verification.
4. Expand **Controller & calibration**, choose the authorized address, and enter the same random device API key configured in the ESP32 (16–256 printable characters, no spaces). Keys are encrypted using the server secret and never returned to the browser. Preserve `secret.key` with backups. Leaving the key field empty keeps the saved key; changing the device address requires a new key.
5. Set A1's X/Y position, horizontal/vertical drawer pitch, extra Y gap between sections, retracted/open servo angles, and LED duration. Controls remain disabled until explicitly enabled. The defaults are examples, not measurements for your hardware.
6. Assign parts by clicking a drawer and selecting one or multiple components. Existing contents remain assigned. Set an individual drawer color or choose **Use organizer color** to inherit its organizer color. Multiple component types can share a drawer. Assignment moves the component's existing storage location without changing its quantity.

Only workspace owners/admins configure hardware. Members may assign parts and operate it. Viewers can inspect the map only. Public demo visitors cannot access physical controls.

## Coordinates

Rows run top to bottom (A–Z, then AA, AB, etc.); columns run left to right. With the default layout, the upper section is A–H and the lower is I–P. Firmware should validate coordinates against its calibrated physical limits rather than assuming an 8×16 layout.

```text
x = x_origin + (column - 1) * x_pitch
 y = y_origin + (row - 1) * y_pitch + section_gap * floor((row - 1) / rows_per_section)
```

`section_gap` is the **extra** distance beyond the normal row spacing at every section boundary (H/I for the default layout). Negative pitch reverses the corresponding axis; use a matching signed gap. Values are millimeters. The firmware converts millimeters to motor steps using its own calibrated steps/mm, acceleration, travel limits, and homing configuration.

## HTTP protocol: partshelf-drawers-v1

All requests carry:

```http
Authorization: Bearer <device-api-key>
```

Validate the key before accepting any command. Return JSON with `Content-Type: application/json`. Responses must be no larger than 8 KB. Redirects are not followed. Partshelf uses a 3-second connection timeout and a 5-second read timeout, so acknowledge quickly and execute asynchronously.

### Submit an action

`POST /api/commands`

```json
{
  "protocol": "partshelf-drawers-v1",
  "command_id": "ff44f45b-d127-47a3-8f74-3a1c77656811",
  "action": "open",
  "drawer": {"row": 9, "column": 8, "label": "I8"},
  "position_mm": {"x": 290.0, "y": 355.0},
  "servo": {"closed_degrees": 10, "open_degrees": 90},
  "light_seconds": 15
}
```

Actions:

- `light`: retract the servo, move the carriage to X/Y, illuminate the drawer for `light_seconds`, then turn the LED off. Do not actuate the drawer-opening movement.
- `open`: retract the servo before XY movement, move to X/Y, illuminate, perform the servo opening movement, and retract before reporting completion. Firmware controls servo dwell timing to suit the mechanism. It must not begin another XY movement with the servo extended.

Return HTTP 202 as soon as the command is validated and stored:

```json
{"command_id":"ff44f45b-d127-47a3-8f74-3a1c77656811","status":"accepted"}
```

HTTP 200 with the same format is also accepted. Supported statuses: `accepted`, `running`, `completed`, `failed`. Report `failed` only after motion has stopped and the command cannot execute later. `completed` means the physical action finished, not merely that it was queued.

### Read status

`GET /api/commands/<command_id>` returns HTTP 200 with the same ID and its current status. Partshelf polls every two seconds while the page is open, up to 30 attempts; **Check status** resumes polling. Status requests must not initiate motion. Keep a durable command journal so reconnects/reboots cannot replay an old opening action. Unknown IDs may return 404; the website then preserves the lock as uncertain.

### Execution and failure rules

- Enforce one active command at a time in the controller, even if another client bypasses Partshelf.
- Deduplicate UUID command IDs: a duplicate POST returns the stored status and must never execute twice.
- Validate protocol, actions, coordinates, servo bounds, and actual mechanical travel limits. Reject motion until homing is complete. Re-home as required after a reset or lost steps.
- Implement physical limit switches and a physical emergency stop. The website is not a real-time motor controller or an emergency stop.
- Partshelf does not automatically retry POSTs. Timeout, malformed response, wrong command ID, or HTTP error leaves the cabinet locked with an **unknown** status because motion may have started.
- The website stores the lock before sending the request, so it survives reloads and worker restarts. Settings cannot change while a command is active.
- If the device cannot report a terminal status, an owner/admin may reload the cabinet page and clear the lock under **Controller & calibration** only after physically checking that the controller has stopped and cannot later execute that command. Clearing this lock sends no device request and does not stop motors.

The recent-command table records action, drawer, status, actor ID in the database, and UTC timestamps. It does not store the device key in the command payload. No firmware or physical motion is tested by automated website tests.

## Storage and sidebar

Organizers count as one storage area each; internal drawers are not listed separately on the Storage areas page. Drawer locations remain available in component editors and inventory filters. In **Settings → Your sidebar**, select storage-area or organizer names to add shortcuts, then reorder them with the arrows. These shortcuts are personal to the signed-in user and scoped to the current workspace. Hardware action buttons are hidden until controls are enabled under **Controller & calibration**.
