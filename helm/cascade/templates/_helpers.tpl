{{/*
Template helpers shared across cascade resource templates.
*/}}

{{/*
Fully-qualified name for resources, capped at 63 chars per K8s convention.
Used as the prefix for every resource this chart creates.
*/}}
{{- define "cascade.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Per-component name: cascade-api, cascade-mcp, cascade-ui.
Called as: include "cascade.componentName" (dict "context" . "component" "api")
*/}}
{{- define "cascade.componentName" -}}
{{- printf "%s-%s" (include "cascade.fullname" .context) .component | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Chart name + version label value.
*/}}
{{- define "cascade.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Standard labels applied to every resource. The component-specific name is
added on top via the per-resource template.
*/}}
{{- define "cascade.labels" -}}
helm.sh/chart: {{ include "cascade.chart" . }}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: cascade
{{- end }}

{{/*
Selector labels — subset of the standard labels that identify a pod's
owning resource. Must remain stable across rolling updates.
Called as: include "cascade.selectorLabels" (dict "context" . "component" "api")
*/}}
{{- define "cascade.selectorLabels" -}}
app.kubernetes.io/name: {{ .context.Chart.Name }}
app.kubernetes.io/instance: {{ .context.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
ServiceAccount name. When .Values.serviceAccount.create is true, the chart
creates the SA; otherwise it expects one named .Values.serviceAccount.name.
*/}}
{{- define "cascade.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "cascade.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Secret name. When .Values.secrets.existingSecret is non-empty, the chart
references it; otherwise it creates a Secret named cascade-secrets.
*/}}
{{- define "cascade.secretName" -}}
{{- if .Values.secrets.existingSecret }}
{{- .Values.secrets.existingSecret }}
{{- else }}
{{- printf "%s-secrets" (include "cascade.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Image string for a component. Falls back to the chart-level image when
the per-component override is empty.
Called as: include "cascade.image" (dict "context" . "component" .Values.api)
*/}}
{{- define "cascade.image" -}}
{{- $repo := default .context.Values.image.repository .component.image.repository -}}
{{- $tag := default .context.Values.image.tag .component.image.tag -}}
{{- $tag := default .context.Chart.AppVersion $tag -}}
{{- printf "%s:%s" $repo $tag }}
{{- end }}

{{/*
DATABASE_URL value, resolving to the in-chart Postgres when enabled, or
the externalDatabase config when not. The Postgres password is read from
a Secret regardless — the URL itself doesn't carry it; the deployment
spec mounts the password as an env var and the app composes the URL at
startup.

For simplicity we emit a URL with a literal $POSTGRES_PASSWORD placeholder
that the container's entrypoint substitutes at runtime. Helm interpolates
the rest.
*/}}
{{- define "cascade.databaseUrl" -}}
{{- if .Values.postgresql.enabled -}}
postgresql+psycopg://{{ .Values.postgresql.auth.username }}:$(POSTGRES_PASSWORD)@{{ include "cascade.fullname" . }}-postgresql:5432/{{ .Values.postgresql.auth.database }}
{{- else -}}
postgresql+psycopg://{{ .Values.externalDatabase.user }}:$(POSTGRES_PASSWORD)@{{ .Values.externalDatabase.host }}:{{ .Values.externalDatabase.port }}/{{ .Values.externalDatabase.database }}
{{- end }}
{{- end }}

{{/*
The Secret name + key that carries the Postgres password. Different
sources depending on postgresql.enabled and externalDatabase config.
Emits a tuple: secretName,passwordKey
*/}}
{{- define "cascade.databasePasswordSecret" -}}
{{- if .Values.postgresql.enabled -}}
  {{- if .Values.postgresql.auth.existingSecret -}}
    {{ .Values.postgresql.auth.existingSecret }},password
  {{- else -}}
    {{ include "cascade.fullname" . }}-postgresql,password
  {{- end -}}
{{- else -}}
  {{ .Values.externalDatabase.existingSecret }},{{ .Values.externalDatabase.existingSecretPasswordKey }}
{{- end -}}
{{- end }}
