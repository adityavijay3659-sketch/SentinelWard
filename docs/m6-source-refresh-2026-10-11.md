# M6 source refresh — 11 October 2026

The project Drive now lists 26 direct children, including new 10 October
documents. The current README, locked v1 contract, Aditya/lead/Singhal/Antara
plans, data notes, ward script, readiness notes and LinuxONE practice results
were read. This updates the historical 9 October resumption audit; it does not
turn a team plan or reported practice measurement into checkout acceptance.

The [website](https://sentinelward-inside.vercel.app/#/ring) now loads
`/assets/index-DaHYyF5z.js`. Its source includes the revised dataset and
patient-specific gap design. This was an HTTP/source inspection, not a rendered
UI or live backend test. The preserved snapshot is
`D:/SentinelWard-M6-Fix-20261009/website-index-20261011.js`, SHA-256
`b7c5e06368857c66f466749213acc01385b46be009d1d4a00acdb5b1cebbe0a3`.

| Updated source | Implication for this checkout |
|---|---|
| [Locked v1 contract](https://docs.google.com/document/d/1oY7ey-ITYLh76afri2GZ6TKlAKCh8DXkPoVWBgE1F4I/edit) | Ownership, topics and JSON formats remain locked; missing is null and patient review retains precedence. No wire changes were made. |
| [Aditya's updated plan](https://docs.google.com/document/d/1g607UAj0qesELA4680IGhnaUZwQg4RjkUWsgmImgdS4/edit) and [data notes](https://docs.google.com/document/d/1bEMTIoP1f9x2sEtBPIesZNZW4_5-CVU7Sp4O85_uN7M/edit) | Compare each patient's line–cuff gap with their own reference, and check arterial-line metadata. The current scorer's absolute-gap component does not implement that new personalization. |
| [LinuxONE practice results](https://docs.google.com/document/d/1tt4SeUYELCqgt9N85cnZEuK72tOWqFlOInbSaqgJyXA/edit) | The team reports successful separate practice work on z17, including larger build-server resources. SentinelWard's wheel, migrations, dependencies, 12-bed timing and live delivery were not independently run on that server here. |
| [Ward script](https://docs.google.com/document/d/1z0aEjihQrE7EuBQyI3UGBkV1MPdTpab0fJKTQnOPMd8/edit) | B08/B09/B10 scenarios are planned acceptance fixtures; their expected timings/verdicts are not results of our current harness. |
| [README v4](https://docs.google.com/document/d/1DkydynqUffO-nGMkcH0oaRNfRQSFOKCsYgQmHPTjiv4/edit) | Event-window instructions remain in team documents. Existing local research was continued under the user's explicit request; event submission eligibility was not adjudicated or claimed. |

The source refresh does not authorize Granite-generated live wording. The user's
deterministic outputs and fixed templates remain required, even where practice
notes describe a faster Granite model.

The local metadata audit found nonempty `aline1` entries for **all 24 already
selected cases**, 12 in each cohort. This establishes what the local metadata
records, not clinical truth or equivalence to the team's PhysioNet copy. The
team's notes distinguish its `.vital` release from API-based downloads; their
source versions and channel/time interpretation must be reconciled before the
next pilot. The current cohort builder does not explicitly filter `aline1`.

`updated-source-gap-audit-20261011.json` contains selection/metadata digests and
descriptive gaps from the four previously inspected paired-reference patients.
It samples one derived gap per distinct inferred cuff timestamp, rather than
counting every held-value exposure independently. One patient's signed median
was −16.649 mmHg across only four observed updates; every sampled event there
also triggered a patient-review guard. This cannot establish a healthy offset,
natural drift, false-alarm rate or a valid calibration. Whole-record medians
would also use future observations if treated as live baselines.

The next accuracy experiment must compare the frozen absolute-gap reference
with a **causal, patient-specific signed-gap change** component. Collect a
separate quality-reviewed reference at distinct verified cuff acquisitions;
freeze it before evaluating later deviations. Define observation counts,
duration, variability, expiry and reacquisition on development/validation data.
Do not infer that a large initial gap is healthy, absorb an existing fault into
calibration or calibrate from urgent observations. Keep the existing low-pressure,
relative-fall and high-alarm review guards ahead of any personalized comparison.
Unknown calibration must abstain from a personalized drift conclusion.

That experiment must also separate cuff-event readiness from waveform/timing
baseline readiness, measure coverage and delay including unavailable events,
and retain genuine reviewed deterioration and stable cases in the safety/false
alarm denominators. It requires a new versioned research candidate, calibration
transition and score-consumer review before runtime replacement. No such model
replacement or clinical accuracy improvement is claimed in version 0.3.4.
