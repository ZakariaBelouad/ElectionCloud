# ElectionCloud

Local academic prototype for polling-station voting. Use fictional voter references and candidates. The CLI assumes the operator has already verified voter eligibility. All commands run with the permissions of the local operator.

## Run the demo

Requires Python 3.10 or newer. From this directory:

```powershell
python -m pip install -r requirements.txt
python electioncloud.py init --private-key tally.pem "Candidate A" "Candidate B"
python electioncloud.py candidates
python electioncloud.py issue DEMO-001
python electioncloud.py vote 1
python electioncloud.py turnout
python electioncloud.py close
python electioncloud.py tally --private-key tally.pem
```

Paste the token printed by `issue` when `vote` prompts for it. The vote command prints confirmation after SQLite commits the encrypted ballot and consumes the session in one transaction. The turnout command reports accepted ballots. The tally command requires closure and the matching private key.

### Resume or start a fresh demo

Run `init` once per database. If `election.db` already exists, use `candidates` and `turnout` to check the current election, then continue with `issue` if it is open. SQLite stores `election.db` in a binary format, so VS Code's text editor displays control characters when you open it.

To start a separate demo, choose unused database and key filenames:

```powershell
python electioncloud.py --db demo2.db init --private-key demo2.pem "Candidate A" "Candidate B"
python electioncloud.py --db demo2.db candidates
```

Pass `--db demo2.db` before each command for that election, and use `--private-key demo2.pem` when tallying.

## Scope

### Docker Compose demo

With Docker Desktop running, open PowerShell in the ElectionCloud directory:

```powershell
docker compose build web worker
docker compose run --rm --no-deps admin init --private-key /keys/tally.pem "Candidate A" "Candidate B"
docker compose up -d --wait
```

Run `init` once per Compose project. On later starts, run `docker compose up -d --wait`. Open http://127.0.0.1:8767. Issue a session using a fictional reference such as `DEMO-001`, cast a ballot, and use **Check ballot receipt** with the same token if the ballot is still queued. Check the worker log with `docker compose logs worker`.

When you are ready to finish the election:

```powershell
docker compose run --rm --no-deps admin close
docker compose run --rm --no-deps admin tally --private-key /keys/tally.pem
docker compose down
```

The web and worker run in separate containers and share the election database in a local Docker volume. The tally key lives in a second volume mounted only by the admin command. The broker has its own volume and is reachable on the Compose network. The published browser port defaults to `8767` and binds to the host loopback interface. Set `$env:ELECTIONCLOUD_PORT = '8768'` before starting if you need a different port. The worker defaults to `broker:9092`; set `ELECTIONCLOUD_BROKER` to override it if using a reachable broker. `docker compose down` preserves all volumes. To run a new election alongside the first, use a different project name with `docker compose -p electioncloud-demo2` for every command and choose a different browser port.

### Browser demo

From this directory, create a fresh election with unused filenames and start the local server:

```powershell
python electioncloud.py --db web-demo.db init --private-key web-demo.pem "Candidate A" "Candidate B"
python web.py --db web-demo.db
```

Open http://127.0.0.1:8765. Issue a session with a fictional reference, copy the token into the ballot form, select a candidate, and confirm. The page displays a receipt and updated turnout. Both forms share the same local page for demonstration. They assume a trusted operator and provide no role-based access control.

To close and tally, run these commands in a second terminal in the same directory:

```powershell
python electioncloud.py --db web-demo.db close
python electioncloud.py --db web-demo.db tally --private-key web-demo.pem
```

Refresh the browser to see the closed state. Stop the server with Ctrl+C. For another run, use unused database and key filenames.

### Kafka demo

#### Start Kafka on Windows

With Java 17 or newer, download the [Apache Kafka 4.4.0 binary archive](https://downloads.apache.org/kafka/4.4.0/kafka_2.13-4.4.0.tgz) and extract it. If you downloaded it to your Downloads folder, run from the ElectionCloud directory:

```powershell
tar.exe -xzf "$env:USERPROFILE\Downloads\kafka_2.13-4.4.0.tgz" -C "$env:USERPROFILE\Downloads"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-kafka.ps1 -KafkaDirectory "$env:USERPROFILE\Downloads\kafka_2.13-4.4.0"
```

Leave this terminal running. On subsequent runs, start the launcher again and it will reuse the same broker storage.

#### Start Kafka with Docker

If you use Docker Desktop, start the engine and run:

```powershell
docker run --rm --name electioncloud-kafka -p 127.0.0.1:9092:9092 apache/kafka:4.4.0
```

#### Start the worker and web app

In a second terminal, from the ElectionCloud directory, install the Kafka client and initialize a fresh demo:

```powershell
python -m pip install -r requirements-kafka.txt
python electioncloud.py --db kafka-demo.db init --private-key kafka-demo.pem "Candidate A" "Candidate B"
python kafka_worker.py --db kafka-demo.db
```

In a third terminal, start the Kafka-enabled web app. Port 8766 lets the earlier browser demo keep running on 8765.

```powershell
python web.py --db kafka-demo.db --port 8766 --kafka
```

Open http://127.0.0.1:8766, issue a session, and submit a ballot. If the page reports **Ballot queued**, keep the token and use **Check ballot receipt**. Turnout only includes stored ballots. When all queued ballots have been stored, close and tally the election:

```powershell
python electioncloud.py --db kafka-demo.db close
python electioncloud.py --db kafka-demo.db tally --private-key kafka-demo.pem
```

In Kafka mode, the web app consumes the session and saves the encrypted submission to a SQLite outbox in one transaction. The worker periodically publishes outstanding rows to an election-specific Kafka topic. The message contains the technical ballot ID as its key and the ciphertext as its value. The worker consumes the message, atomically moves the matching submission into the ballot box, then commits the Kafka offset. Replays have no matching outbox row and cannot add another ballot. Restart the worker if it stops. The SQLite queue survives a restart, and closure waits for queued ballots to drain.

This single-broker setup and shared SQLite database are for local demonstration. Use the browser with `--kafka` to exercise this path. The terminal voting command and browser without `--kafka` use the direct SQLite flow.

### Architecture

#### Cosmos DB storage

To use an existing Azure Cosmos DB for NoSQL account, create a database and a container with partition key `/electionId`. Select a fresh election ID and supply these values in the PowerShell session that runs Compose:

```powershell
$env:ELECTIONCLOUD_STORAGE = "cosmos"
$env:ELECTIONCLOUD_ELECTION_ID = "demo-001"
$env:COSMOS_ENDPOINT = "https://YOUR-ACCOUNT.documents.azure.com:443/"
$env:COSMOS_DATABASE = "electioncloud"
$env:COSMOS_CONTAINER = "elections"
$env:COSMOS_KEY = (Read-Host "Cosmos DB account key" -MaskInput)
$env:ELECTIONCLOUD_PORT = "8768"
```

Use PowerShell 7 for `Read-Host -MaskInput`. Supply cloud credentials through your environment or secret configuration. The environment settings must be available to the web app, worker, and admin command for the same election.

```powershell
docker compose -p electioncloud-cosmos build web worker
docker compose -p electioncloud-cosmos run --rm --no-deps admin init --private-key /keys/tally.pem "Candidate A" "Candidate B"
docker compose -p electioncloud-cosmos up -d --wait
```

Open http://127.0.0.1:8768. Use the same project name to close, tally, and stop this demo. For direct Python commands, install `requirements-cosmos.txt` and, for the worker, `requirements-kafka.txt`. Cosmos mode creates a new election and does not import existing SQLite ballots.

Cosmos keeps voter markers, one-time sessions, outbox entries, and ballots as distinct documents within one logical election partition. Transactional batches consume a session and queue a ballot together. A second batch stores the ballot, drains its outbox entry, and updates turnout before the worker commits the Kafka offset. The shared partition enables atomic updates but limits throughput and provides logical separation only. Treat it as an academic design for synthetic data. Hosted identity, network access, and service deployment are separate from this storage integration.

#### SQLite storage

SQLite stores session records and encrypted ballots in separate tables. Ballot rows contain a random technical ID and encrypted candidate ID. For this local demo, the database and tally key are files controlled by the operator. Keep the unencrypted private key in a restricted location. The close check is enforced by the CLI, and an operator with access to the key and database can decrypt ballots independently. Database or filesystem observers may be able to correlate voting activity. Use this prototype with synthetic data only.

The brief's target deployment uses Azure App Service, Container Apps, Cosmos DB and Key Vault, with Kafka and tally workers on AWS EC2 and notifications and recovery services on AWS and Google Cloud.

See [Deploy ElectionCloud to Azure](AZURE.md) for the deployment script, environment setup, and verification steps.

### Test separate Kafka processes locally

With the broker running and the same demo database selected, start these commands in separate terminals. Start the publisher first so it can create the election topic. Stop the combined worker for that database before running the two processes.

```powershell
python kafka_worker.py --db kafka-demo.db --role publisher
python kafka_worker.py --db kafka-demo.db --role consumer
```

The publisher reads the durable outbox and sends ciphertext to Kafka. The consumer stores the ballot and commits the Kafka offset. The default role is `both`, so the existing Docker Compose and single-worker commands still work.
