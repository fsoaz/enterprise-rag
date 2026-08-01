"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Locale = "en" | "pt";

const en = {
  skip: "Skip to main content",
  language: "Language",
  english: "English",
  portuguese: "Português",
  devUser: "Dev user",
  authChecking: "Checking your session…",
  authUnavailable: "Authentication is unavailable.",
  authErrorProviderDenied: "Sign-in was cancelled or denied by the identity provider.",
  authErrorStateMismatch: "The login response could not be verified. Please try again.",
  authErrorUnauthorized: "The identity is not authorized for this application.",
  authErrorExchangeFailed: "Login could not be completed. Please try again.",
  authErrorGeneric: "Sign-in failed. Please try again.",
  authDescription:
    "Sign in with your organization to access permission-aware answers and documents.",
  signIn: "Sign in",
  signOut: "Sign out",
  chatDescription: "Ask a question grounded in your documents.",
  conversation: "Conversation",
  you: "You",
  assistant: "Assistant",
  question: "Your question",
  questionPlaceholder: "Ask in Portuguese or English…",
  ask: "Ask",
  thinking: "Thinking…",
  stop: "Stop",
  retrieving: "Finding relevant documents…",
  generating: "Drafting the answer…",
  verifying: "Checking support and citations…",
  answerReady: "Answer ready, {count} sources.",
  answerCancelled: "Generation stopped. The answer below is incomplete.",
  requestFailed: "Request failed: {detail}",
  streamFailed: "The answer stream failed.",
  source: "Source",
  unverifiedSource: "Unverified source",
  unsupported: "The system abstained — the corpus does not support a grounded answer.",
  partial: "Partially supported answer — check the cited sources.",
  answer: "Answer",
  jumpSource: "Jump to source {number}",
  helpful: "Helpful",
  notHelpful: "Not helpful",
  feedbackThanks: "Thanks — feedback recorded.",
  feedbackFailed: "Could not send feedback: {detail}",
  sending: "Sending…",
  sources: "Sources",
  chars: "chars",
  stalenessFresh: "Current",
  stalenessStale: "Past review date",
  stalenessSuperseded: "Superseded by a newer version",
  stalenessUnknown: "Currency unknown",
  documentAdmin: "Document admin",
  adminDescription: "Upload PDF, Markdown, or plain text.",
  documentTitle: "Document title",
  titlePlaceholder: "Defaults to the file name",
  collection: "Collection",
  noCollections: "No collections available",
  file: "File",
  upload: "Upload",
  uploading: "Uploading…",
  uploadAccepted: "Upload accepted — ingesting…",
  noJob: "Upload accepted, but no ingestion job was returned. Refresh to check status.",
  stillProcessing: "Still processing — check back shortly and refresh the job status.",
  loadCollectionsFailed: "Could not load collections: {detail}",
  loadDocumentsFailed: "Could not load documents: {detail}",
  loadHistoryFailed: "Could not load ingestion history: {detail}",
  updateDocumentFailed: "Could not update document: {detail}",
  archivedMessage: "Document archived.",
  restoredMessage: "Document restored.",
  ingestStage: "Ingest stage",
  documents: "Documents",
  documentsDescription: "Review ingestion history and control retrieval availability.",
  refresh: "Refresh",
  loadMore: "Load more",
  noDocuments: "No documents are visible in your collections.",
  archived: "Archived",
  active: "Active",
  unknownCollection: "Unknown collection",
  added: "added",
  hideJobs: "Hide jobs",
  viewJobs: "View jobs",
  updating: "Updating…",
  restore: "Restore",
  archive: "Archive",
  loadingHistory: "Loading ingestion history…",
  noJobs: "No ingestion jobs recorded.",
  attempts: "{count} attempts",
  backToChat: "Back to chat",
  aclGrants: "Access grants",
  aclDescription: "Revoke collection or document permissions.",
  aclEmpty: "No ACL entries.",
  aclRevoke: "Revoke",
  aclRevoked: "Grant revoked.",
  aclLoadFailed: "Could not load ACL entries: {detail}",
  aclRevokeFailed: "Could not revoke grant: {detail}",
  legalHold: "Legal hold",
  legalHoldOn: "Place hold",
  legalHoldOff: "Clear hold",
  legalHoldUpdated: "Legal hold updated.",
  legalHoldFailed: "Could not update legal hold: {detail}",
} as const;

type MessageKey = keyof typeof en;

const pt: Record<MessageKey, string> = {
  skip: "Pular para o conteúdo principal",
  language: "Idioma",
  english: "English",
  portuguese: "Português",
  devUser: "Usuário de desenvolvimento",
  authChecking: "Verificando sua sessão…",
  authUnavailable: "A autenticação está indisponível.",
  authErrorProviderDenied: "O login foi cancelado ou negado pelo provedor de identidade.",
  authErrorStateMismatch: "A resposta de login não pôde ser verificada. Tente novamente.",
  authErrorUnauthorized: "A identidade não está autorizada para este aplicativo.",
  authErrorExchangeFailed: "Não foi possível concluir o login. Tente novamente.",
  authErrorGeneric: "Falha no login. Tente novamente.",
  authDescription:
    "Entre com a conta da sua organização para acessar respostas e documentos conforme suas permissões.",
  signIn: "Entrar",
  signOut: "Sair",
  chatDescription: "Faça uma pergunta baseada nos seus documentos.",
  conversation: "Conversa",
  you: "Você",
  assistant: "Assistente",
  question: "Sua pergunta",
  questionPlaceholder: "Pergunte em português ou inglês…",
  ask: "Perguntar",
  thinking: "Pensando…",
  stop: "Parar",
  retrieving: "Buscando documentos relevantes…",
  generating: "Elaborando a resposta…",
  verifying: "Verificando o suporte e as citações…",
  answerReady: "Resposta pronta, {count} fontes.",
  answerCancelled: "Geração interrompida. A resposta abaixo está incompleta.",
  requestFailed: "Falha na solicitação: {detail}",
  streamFailed: "O fluxo da resposta falhou.",
  source: "Fonte",
  unverifiedSource: "Fonte não verificada",
  unsupported: "O sistema se absteve — o acervo não sustenta uma resposta fundamentada.",
  partial: "Resposta parcialmente fundamentada — confira as fontes citadas.",
  answer: "Resposta",
  jumpSource: "Ir para a fonte {number}",
  helpful: "Útil",
  notHelpful: "Não foi útil",
  feedbackThanks: "Obrigado — avaliação registrada.",
  feedbackFailed: "Não foi possível enviar a avaliação: {detail}",
  sending: "Enviando…",
  sources: "Fontes",
  chars: "caracteres",
  stalenessFresh: "Atual",
  stalenessStale: "Prazo de revisão vencido",
  stalenessSuperseded: "Substituído por uma versão mais recente",
  stalenessUnknown: "Atualidade desconhecida",
  documentAdmin: "Administração de documentos",
  adminDescription: "Envie arquivos PDF, Markdown ou texto simples.",
  documentTitle: "Título do documento",
  titlePlaceholder: "Por padrão, usa o nome do arquivo",
  collection: "Coleção",
  noCollections: "Nenhuma coleção disponível",
  file: "Arquivo",
  upload: "Enviar",
  uploading: "Enviando…",
  uploadAccepted: "Envio aceito — processando…",
  noJob: "O envio foi aceito, mas nenhum processamento foi encontrado. Atualize para verificar.",
  stillProcessing: "Ainda processando — volte em instantes e atualize o status.",
  loadCollectionsFailed: "Não foi possível carregar as coleções: {detail}",
  loadDocumentsFailed: "Não foi possível carregar os documentos: {detail}",
  loadHistoryFailed: "Não foi possível carregar o histórico de ingestão: {detail}",
  updateDocumentFailed: "Não foi possível atualizar o documento: {detail}",
  archivedMessage: "Documento arquivado.",
  restoredMessage: "Documento restaurado.",
  ingestStage: "Etapa de ingestão",
  documents: "Documentos",
  documentsDescription: "Revise o histórico e controle a disponibilidade para busca.",
  refresh: "Atualizar",
  loadMore: "Carregar mais",
  noDocuments: "Nenhum documento está visível nas suas coleções.",
  archived: "Arquivado",
  active: "Ativo",
  unknownCollection: "Coleção desconhecida",
  added: "adicionado em",
  hideJobs: "Ocultar processos",
  viewJobs: "Ver processos",
  updating: "Atualizando…",
  restore: "Restaurar",
  archive: "Arquivar",
  loadingHistory: "Carregando histórico de ingestão…",
  noJobs: "Nenhum processo de ingestão registrado.",
  attempts: "{count} tentativas",
  backToChat: "Voltar ao chat",
  aclGrants: "Concessões de acesso",
  aclDescription: "Revogue permissões de coleção ou documento.",
  aclEmpty: "Nenhuma entrada de ACL.",
  aclRevoke: "Revogar",
  aclRevoked: "Concessão revogada.",
  aclLoadFailed: "Não foi possível carregar as entradas de ACL: {detail}",
  aclRevokeFailed: "Não foi possível revogar a concessão: {detail}",
  legalHold: "Retenção legal",
  legalHoldOn: "Colocar retenção",
  legalHoldOff: "Remover retenção",
  legalHoldUpdated: "Retenção legal atualizada.",
  legalHoldFailed: "Não foi possível atualizar a retenção legal: {detail}",
};

const dictionaries: Record<Locale, Record<MessageKey, string>> = { en, pt };

type LocaleContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, values?: Record<string, string | number>) => string;
};

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({
  children,
  initialLocale,
}: {
  children: React.ReactNode;
  initialLocale: Locale;
}) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);

  useEffect(() => {
    document.documentElement.lang = locale === "pt" ? "pt-BR" : "en";
  }, [locale]);

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
    void fetch("/api/locale", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locale: nextLocale }),
    }).catch(() => undefined);
  }, []);

  const t = useCallback(
    (key: MessageKey, values: Record<string, string | number> = {}) =>
      Object.entries(values).reduce(
        (message, [name, value]) => message.replaceAll(`{${name}}`, String(value)),
        dictionaries[locale][key],
      ),
    [locale],
  );
  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const context = useContext(LocaleContext);
  if (!context) throw new Error("useLocale must be used within LocaleProvider");
  return context;
}

export function LocaleSwitch() {
  const { locale, setLocale, t } = useLocale();
  return (
    <label className="text-sm text-neutral-500 dark:text-neutral-400">
      {t("language")}{" "}
      <select
        aria-label={t("language")}
        className="ml-2 rounded border border-neutral-300 bg-transparent px-2 py-1 dark:border-neutral-700"
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        <option value="en">{t("english")}</option>
        <option value="pt">{t("portuguese")}</option>
      </select>
    </label>
  );
}
