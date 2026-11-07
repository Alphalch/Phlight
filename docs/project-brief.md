# Phlight project brief

## Goal

Create a framed 7.3-inch color e-paper picture that turns locally detected aircraft flying overhead into a changing, portrait-style composition. The ADS-B receiver, antenna, and computer must be inside the frame or attached to its rear; no separate receiver box is required.

## Proposed architecture

```text
1090 MHz antenna → integrated ADS-B receiver → Linux ADS-B decoder
    → local aircraft selection → original artwork composition → 7.3-inch display
```

- Use continuous USB power initially. Research battery operation separately rather than promise FlightPortrait-like battery life.
- Consider a Pi Zero 2 W and compact RTL-SDR-compatible hardware; confirm dimensions, power, heat, availability and decoder compatibility before selecting parts.
- Select a 7.3-inch color e-paper panel and compatible driver; confirm portrait orientation, actual resolution, refresh time, electrical interface and physical dimensions.
- Make the rear serviceable and leave an RF-transparent path for a 1090 MHz antenna. Test reception in the actual wall position, not only on a bench.
- Use original or properly licensed aircraft artwork. Aircraft identification and livery data sources must be chosen with their license, reliability and privacy constraints documented.
- Start with a local-only system. Wi-Fi configuration or optional network lookups may be added later; the core receive-to-display path must not depend on a vendor service.

## Success criteria

1. With real receiver hardware mounted in or on the frame, observe real ADS-B messages and position reports in its intended position. Document antenna and range limitations.
2. Select aircraft using a documented home position and distance rule; reject stale or positionless reports instead of representing them as overhead.
3. Render an original portrait at the chosen panel's actual dimensions, including a clear empty-sky state. Demonstrate with recorded fixtures and real receiver data.
4. Refresh the physical 7.3-inch panel from the local renderer and document cadence, power and screen constraints.
5. Assemble a safe, serviceable single frame. Document fit, antenna arrangement, temperature, measured power and power supply requirements.
6. Provide reproducible setup, tests, legal notices and a bill of materials with actual selected parts. Do not claim hardware validation until performed.

## Open decisions and risks

- Exact screen, driver, computer, receiver and antenna; no purchases have been made.
- Frame depth, thermal limits and indoor RF reception require measured hardware tests.
- The Pi Zero 2 W has one USB data port; physical connection of a receiver, power and display must be checked for the chosen parts.
- An SDR receives signals, not necessarily a full aircraft type, operator, or livery. An additional licensed metadata source or a generic fallback may be needed.
- Aircraft send incomplete or inaccurate data, and local reception cannot guarantee every aircraft overhead.
- FlightPortrait poster artwork is proprietary. Do not reuse it without permission; check licenses before reusing any reference firmware or data.

## Delivery

Track independent research and implementation on the `phlight` Kanban board and publish reviewed changes to the private `Alphalch/Phlight` repository. This brief is an initial direction, not evidence of a working device.
