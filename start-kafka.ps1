param(
    [string]$KafkaDirectory = (Join-Path $PSScriptRoot '../../work/kafka_2.13-4.4.0')
)

$ErrorActionPreference = 'Stop'
$java = (Get-Command java.exe -ErrorAction Stop).Source
if (!(Test-Path -LiteralPath (Join-Path $KafkaDirectory 'config/server.properties'))) {
    throw "Kafka was not found at '$KafkaDirectory'. Extract the Apache Kafka binary archive and pass -KafkaDirectory."
}

Push-Location -LiteralPath $KafkaDirectory
try {
    $configPath = 'config/electioncloud-local.properties'
    $config = Get-Content -Raw -LiteralPath 'config/server.properties'
    $config = $config -replace '(?m)^listeners=.*$', 'listeners=PLAINTEXT://127.0.0.1:9092,CONTROLLER://127.0.0.1:9093'
    $config = $config -replace '(?m)^advertised.listeners=.*$', 'advertised.listeners=PLAINTEXT://127.0.0.1:9092,CONTROLLER://127.0.0.1:9093'
    $config = $config -replace '(?m)^controller.quorum.bootstrap.servers=.*$', 'controller.quorum.bootstrap.servers=127.0.0.1:9093'
    $config = $config -replace '(?m)^log.dirs=.*$', 'log.dirs=electioncloud-data'
    Set-Content -LiteralPath $configPath -Value $config -Encoding ascii

    if (!(Test-Path -LiteralPath 'electioncloud-data/meta.properties')) {
        $clusterId = & $java -cp 'libs/*' kafka.tools.StorageTool random-uuid
        if ($LASTEXITCODE -ne 0) { throw 'Could not generate the Kafka cluster ID.' }
        & $java -cp 'libs/*' kafka.tools.StorageTool format --standalone -t $clusterId -c $configPath
        if ($LASTEXITCODE -ne 0) { throw 'Could not initialize Kafka storage.' }
    }
    & $java -Xms256M -Xmx768M '-Dlog4j2.configurationFile=config/log4j2.yaml' -cp 'libs/*' kafka.Kafka $configPath
    if ($LASTEXITCODE -ne 0) { throw "Kafka exited with code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
