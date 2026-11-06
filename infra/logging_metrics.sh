cat << 'EOF' > /tmp/metric_tokens.yaml
name: agent_session_total_tokens
description: Total tokens consumed per agent session
filter: 'jsonPayload.event_type="agent_execution_telemetry"'
valueExtractor: 'EXTRACT(jsonPayload.total_tokens)'
metricDescriptor:
  metricKind: DELTA
  valueType: DISTRIBUTION
  unit: '1'
bucketOptions:
  linearBuckets:
    numFiniteBuckets: 20
    width: 250
    offset: 0
EOF

gcloud logging metrics create agent_session_total_tokens \
  --config-from-file=/tmp/metric_tokens.yaml \
  --project=data4ai-challenge-03






cat << 'EOF' > /tmp/metric_tokens_with_label.yaml
name: agent_session_total_tokens
description: Total tokens consumed per agent session with session_id grouping
filter: 'jsonPayload.event_type="agent_execution_telemetry"'
valueExtractor: 'EXTRACT(jsonPayload.total_tokens)'
metricDescriptor:
  metricKind: DELTA
  valueType: DISTRIBUTION
  unit: '1'
  labels:
  - key: session_id
    valueType: STRING
    description: Identifier of the agent session
labelExtractors:
  session_id: 'EXTRACT(jsonPayload.session_id)'
bucketOptions:
  linearBuckets:
    numFiniteBuckets: 20
    width: 250
    offset: 0
EOF

gcloud logging metrics update agent_session_total_tokens \
  --config-from-file=/tmp/metric_tokens_with_label.yaml \
  --project=data4ai-challenge-03






cat << 'EOF' > /tmp/metric_latency.yaml
name: agent_execution_latency_ms
description: Execution latency in milliseconds
filter: 'jsonPayload.event_type="agent_execution_telemetry"'
valueExtractor: 'EXTRACT(jsonPayload.latency_ms)'
metricDescriptor:
  metricKind: DELTA
  valueType: DISTRIBUTION
  unit: 'ms'
bucketOptions:
  exponentialBuckets:
    numFiniteBuckets: 20
    growthFactor: 1.5
    scale: 20.0
EOF

gcloud logging metrics create agent_execution_latency_ms \
  --config-from-file=/tmp/metric_latency.yaml \
  --project=data4ai-challenge-03



