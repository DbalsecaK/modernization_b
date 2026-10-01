{{- define "nexti.fullname" -}}{{ .Release.Name }}{{- end -}}

{{- define "nexti.image" -}}
{{- $root := index . 0 -}}{{- $name := index . 1 -}}
{{ $root.Values.image.registry }}/{{ $name }}:{{ $root.Values.image.tag | default $root.Chart.AppVersion }}
{{- end -}}

{{- define "nexti.labels" -}}
app.kubernetes.io/part-of: nexti
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "nexti.podSecurity" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "nexti.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{- define "nexti.env" -}}
- name: APP_ENV
  value: {{ .Values.appEnv | quote }}
- name: WEB_ORIGIN
  value: {{ .Values.webOrigin | quote }}
- name: KEYCLOAK_URL
  value: {{ .Values.services.keycloakUrl | quote }}
- name: KEYCLOAK_PUBLIC_URL
  value: {{ .Values.keycloakPublicUrl | quote }}
- name: SECRETS_URL
  value: {{ .Values.services.secretsUrl | quote }}
- name: OBJECT_STORE_URL
  value: {{ .Values.services.objectStoreUrl | quote }}
- name: OPENFGA_URL
  value: {{ .Values.services.openfgaUrl | quote }}
- name: OPENFGA_STORE_ID
  value: {{ .Values.openfga.storeId | quote }}
- name: OPENFGA_MODEL_ID
  value: {{ .Values.openfga.modelId | quote }}
- name: OPENFGA_BOOTSTRAP
  value: {{ .Values.openfga.bootstrap | quote }}
- name: GRAPH_URI
  value: {{ .Values.services.graphUri | quote }}
- name: MALWARE_SCANNER_HOST
  value: {{ .Values.services.malwareScannerHost | quote }}
- name: MALWARE_SCANNER_PORT
  value: {{ .Values.services.malwareScannerPort | quote }}
- name: OSV_URL
  value: {{ .Values.services.osvUrl | quote }}
- name: SESSION_COOKIE_SECURE
  value: "true"
{{- end -}}
