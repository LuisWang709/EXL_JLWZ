# Demo recording outline: approximately 2 minutes 50 seconds

This outline shows an already processed M001 example. Show historical decisions as historical decisions. Loading/waiting segments may be cut. If using a mock LLM, label the opening frame "Mock LLM demo". Label scripted decisions "Demo approval records".

| Time | Recording action | Spoken English |
| --- | --- | --- |
| 0:00-0:12 | Overview: point to model, pending-review, and alert counts | This is Model Risk Factory. It helps banks document old models, check their results, and watch for problems over time. |
| 0:12-0:24 | Expand the new-model upload form; point to code/development/validation inputs. Do not start another pipeline | Users upload model code and data here. Next, we will look at a loan-risk model that has already been processed. |
| 0:24-0:36 | Models: select M001, Classification; show language, algorithm, purpose | The system first identifies the model. This one is written in SAS and predicts whether a loan will default. |
| 0:36-0:49 | Documentation: scroll through purpose/method/limits and point to evidence references | AI then writes a document explaining how the model works and its limits. References help us find the supporting evidence. |
| 0:49-1:00 | Show the document rating table: rules/60, reviewer/40, passed | Rules and an AI reviewer check the document. This score measures the quality of the document. |
| 1:00-1:11 | Review queue: show the model's recorded H1 decision in Recent decisions | H1 is the first human review: checking whether the document is correct. The reviewer and decision are recorded here. |
| 1:11-1:24 | Models, M001, Python rebuild: expand existing Rebuilt Python code near def score; do not start another rebuild | Next, the system produces Python scoring code. The goal is to keep the original calculation and produce the same results in Python. |
| 1:24-1:40 | Point to records, mismatches, max abs diff, then Parity certificate | The system checks each result and saves a certificate. These reference scores were simulated in Python. Independent checks still need real SAS or R outputs. |
| 1:40-1:55 | Reports: choose validation; show performance, stability, fairness | The report checks prediction quality, changes in the data, and differences between groups. The numbers come from calculation tools. |
| 1:55-2:05 | Point to an actual finding or unassessed dimension; otherwise show the conclusion without inventing a problem | Matching the old model can still mean poor performance. The report lists problems and marks checks with missing evidence as unassessed. |
| 2:05-2:15 | Review queue: show recorded H2 decision. If M001 currently awaits H2, show its Validation report and pending state without approving it just for the video | H2 is the second human review. A person checks the validation results and decides whether the model can be used. |
| 2:15-2:27 | Monitoring: select M001 and show the existing PSI trend | When new data arrives, the system checks again. These synthetic batches show how changes can be detected. |
| 2:27-2:39 | Alerts: select a red drift alert, expand evidence/handling history, show cause and revalidation task | When the change is too large, the system raises an alert and sends the new batch back for validation and another human review. |
| 2:39-2:50 | Select a data_quality alert, show why its batch was rejected, end on the evidence/handling record | If the data has serious problems, that batch is rejected before scoring. The workflow keeps evidence of what happened and why. |

For a live approval shot, use only a real pending review after inspecting its material. Never approve a red report merely to advance the recording. Replace the relevant historical-record shot with one of these alternatives:

| Shot | Action | Spoken English |
| --- | --- | --- |
| H1 live | Read the document, enter the actual review comment, click that task's Approve, show success | After checking the document, I approve it. The system records the decision and continues to the Python rebuild. |
| H2 live | Read Validation report, record the decision/conditions, approve only if the result is accepted | After checking the results, I record the review decision. Once approved, the system registers the model and sets up monitoring. |

The bilingual recording companion is local-only at local/doc/demo-script.md.
