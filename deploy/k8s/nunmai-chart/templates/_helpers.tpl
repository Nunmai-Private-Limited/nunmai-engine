{{- define "nunmai.name" -}}nunmai-{{ .Values.customer }}{{- end -}}
{{- define "nunmai.secretName" -}}{{ default (printf "%s-secrets" (include "nunmai.name" .)) .Values.secrets.existingSecret }}{{- end -}}
{{- define "nunmai.labels" -}}
app.kubernetes.io/name: nunmai-engine
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
nunmai.in/customer: {{ .Values.customer | quote }}
{{- end -}}
