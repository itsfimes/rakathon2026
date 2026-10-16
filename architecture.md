# Backend architecture - written by an actual human 
The whole mindset is to be module focused and mash intersystems technology wherever we can. 

The system is split into blocks. Each block is a function that does something. It has at least one input and one output connector.

### Blocks
Blocks are the core of the system. They are the actual work doing parts of the projects - databases, translators, frontend, LLM hosts etc.
A block is not limited in what it can do, but it should be limited to one function only - an AI server, a database etc.
Each block must feature at least two connectors - one input and one output.


### Connectors 
Connectors wire everything together. They make the whole system communicate.

There are three main defining features for connectors:
 - **INPUT**/**OUTPUT**
 - **FHIR**/ **proprietary** / **metadata**
    - FHIR is patient data,
    - Metadata are misc. in-program comms. and must not carry any sensitive data
    - Proprietary = any data that may contain sensitive data, but is not FHIR. Example:
      ```json
      {"contentType": "application/pdf", "filename": "discharge_report.pdf", "sourceSystem": "HIS-Navision", "bytesRef": "ipc-blob://b1/9f3a2c1e"}
      ```
 - **IPC**/**IP**
    - _IPC_ signals that the connector only accepts in-program communication done through unix sockets
    - _IP_ signals that the connector only accepts information received over the internet 
    - **NOTE**: IPC is always preffered 

- Each connector input or output must have a health ping function 
    - on IP connectors, pinging `/health` on the connector must return 200, if the connector is healthy. It must return a descriptive HTTP error code on failure. Or nothing.
    - IPC connectors expose ping() returning HEALTHY/DEGRADED/DOWN; the check also verifies socket file existence and write/read readiness.
- Connectors must refuse unauthenticated IP requests. Services inputting or requesting output from connectors must have sufficient permissions to do so. 

## Blocks in the current architecture
What actually needs to be implemented. The system has 6 blocks, B1-B6, each with a single function.

#### B1 
- **Connectors**
    - _IN1_:
        - Input, proprietary, IPC 
        - Used to receive information from the frontend's host 
    - _OUT1_:
        - Output, FHIR, IPC
        - Used to output information back to the frontend's host 
    - _OUT2_:
        - Output, proprietary, IPC 
        - Requests translation via the single AI gateway B5 (B5 IN1); the result returns on IN2. No direct IP egress from B1.
    - _IN2_:
        - Input, proprietary, IPC 
        - Receives translated output back from B5 (B5 OUT1).

- Proprietary hospital data types -> FHIR translation layer 
- Combined LLM harness + OCR engine
    - Generic for now, non-llm hospital specific version coming, if actually in prod 
    - Endpoint must be openai-compatible 
- B1 never calls the internet directly; the only IP egress in the whole system is B5. B1 sends IDs-only references (bytesRef, never raw blobs where avoidable) and respects the central kill-switch enforced by B5.

#### B2 
- **Connectors**:
    - _IN1_:
        - Input, FHIR, IPC 
        - Insert FHIR into DB, receives FHIR data and inserts them 
    - _IN2_:
        - Input, metadata, IPC 
        - Receives database queries and forwards them to have their output outputted on:
            - OUT1 for SQL
            - OUT2 for Vector
        - Handles both vector and SQL db requests 
        - Must have proper auth
    - _IN3_:
        - Input, metadata, IPC 
        - Returns job status and metadata relevant for the frontend - what are patients waiting for etc.
    - _IN4_
        - Input, metadata, IP 
        - Returns database status, running jobs etc. on OUT3
    - _OUT1_:
        - Output, FHIR, IPC 
        - Outputs query results from IN2 
        - Outputs patient data, also verifies auth.
    - _OUT2_
        - Output, proprietary, IPC 
        - Outputs results from vector DBs. ONLY anonymized vector DB; non-anonymized data exclusively via OUT1 + auth.
    - _OUT3_:
        - Output, metadata, IP 
        - Returns DB status

- Full spec TBD 
- B2 is a thin IRIS wrapper: no own logic, just passthrough to IRIS FHIR REST + SQL Builder + Vector.
- This is the heart of the whole project - intersystems db's holding all data. SQL and vectorized
    - SQL with FHIR patient data 
    - 2 vectorized DB's one with anonymized patient data, one with non-anonymized patient data. 
    - SQL holding current tasks
        - Holds who is responsible for the task 
        - And ACK status for related users

#### B3 
- **Connectors**: 
    - _IN1_: 
        - Input, FHIR, IPC 
        - Receives patient data query responses from DB's (B2's) single OUT1, matched by correlationId 
    - _IN2_:
        - Input, metadata, IPC 
        - Receives task data query responses from DB's (B2's) single OUT1, matched by correlationId
    - _OUT1_:
        - Output, metadata, IPC 
        - Sends queries for patient data and tasks status to DB's (B2's) IN2 as `OUT1 (B3) --query {correlationId}--> IN2 (B2)`; the response on B2 OUT1 carries the same correlationId.
    - _OUT2_:
        - Output, proprietary, IPC 
        - Sends reminders to frontend to remind users of late running tasks 
- B3 holds a single physical listen on B2 OUT1 and demultiplexes responses by correlationId to the IN1/IN2 handlers. Pull, not listen: B3 initiates every fetch with an OUT1 query; it never relies on B2 pushing unsolicited data.

- Task watchdog; raises flags when tasks are running late - MDT review not happening when it should, patient check-ins delayed etc. 
- Verifies ACK status of tasks 
- Runs periodically
- Manager of the group

#### B4 
- **Connectors**:
    - _IN1_:
        - Input, proprietary, IPC 
        - Receives reminders from B3 
    - _IN2_:
        - Input, FHIR, IPC 
        - Receives FHIR DB data

    - _IN3_: 
        - Input, proprietary, IPC 
        - Receives DB vector search data 
    
    - _IN4_:
        - Input, FHIR, IPC 
        - Receives B1 data

    - _IN5_:
        - Input, proprietary, IPC 
        - Receives input from the AI engine

    - _OUT1_:
        - Output, metadata, IPC 
        - Generic querier for B2

    - _OUT2_:
        - Output, proprietary, IPC 
        - Forwards requests to the AI engine 

    - _OUT3_:
        - Output, proprietary, IPC 
        - Sends proprietary hospital data to B1 for translation
    - _OUT4_:
        - Output, metadata, IPC 
        - Auth query to B6 (B6 IN1) as {userId, action}; verdict returns on IN6.
    - _IN6_:
        - Input, metadata, IPC 
        - Receives allow/deny verdict from B6 (B6 OUT1).

- This block hosts and handles all comms with the frontend. It is a router: it accepts ingress messages, looks up the internal `requestId -> requesting block` map, and forwards each message to the correct egress. Routing table:
    - IN1 (B3 reminders) -> frontend host channel
    - IN2 (FHIR DB data) -> OUT1 (response to a B2 query)
    - IN3 (vector search data) -> OUT1 (response to a B2 query)
    - IN4 (B1 data) -> frontend host channel
    - IN5 (AI engine input) -> OUT2 (request to the AI engine)
- B4 refuses unauthenticated IP requests and authorizes every action via B6 before routing.

#### B5
- **Connectors** 
    - _IN1_:
        - Input, proprietary, IPC 
        - Receives input from other modules to forward to an AI
    - _AI.IN2_:
        - Input, proprietary, IP 
        - Receives output from the AI 
    - _OUT1_:
        - Output, proprietary, IPC 
        - Hands back output from the AI, into the block that requested it 
    - _AI.OUT2_:
        - Output, proprietary, IP 
        - Sends prompts from IN1 into the remote AI 

- This block is a gate between a remote AI provider and the local app. It is the single AI gateway and the only IP egress in the whole system.
- Runs opencode instances, handles the requests there. Prompt management, auth, and the central kill-switch live here in one place.

#### B6
- **Connectors**
    - _IN1_:
        - Input, metadata, IPC 
        - Receives auth query from B4 (B4 OUT4) as {userId, action}.
    - _OUT1_:
        - Output, metadata, IPC 
        - Returns verdict allow/deny to B4 (B4 IN6).
- Access/permissions module: holds the user list + role matrix. B4 queries it on every action; TODAY a MOCK matrix.json is acceptable.
