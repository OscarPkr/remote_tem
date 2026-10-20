from pathlib import Path
from tests.helpers.document_source import document_source
from tests.helpers.js_modules import email_library_source, js_function_source


_REPO = Path(__file__).resolve().parents[1]
_EMAIL_ROUTES = _REPO / "routes" / "email" / "email_routes.py"
_EMAIL_MCP_SERVER = _REPO / "mcp_servers" / "email_server.py"
_EMAIL_FIXTURE_HELPER = _REPO / "scripts" / "ody_eval_email_fixture.py"


def _bulk_action_source() -> str:
    return js_function_source("_bulkAction")


def _function_source(name: str) -> str:
    return js_function_source(name)


def test_email_bulk_read_unread_calls_provider_write_routes():
    """Bulk read/unread must persist to IMAP/provider, not only mutate UI state.

    Regression for issue #800's email follow-up: list select -> Actions ->
    Mark Read used to update `em.is_read` locally and cache that fake state,
    then refresh from the provider made the message unread again.
    """
    src = _bulk_action_source()

    assert "Local toggle for now" not in src
    assert "mark-read" in src
    assert "mark-unread" in src
    assert "method: 'POST'" in src
    assert "_syncEmailReadState(uid, action === 'read')" in src


def test_email_bulk_read_unread_checks_backend_success_before_syncing_cache():
    src = _bulk_action_source()

    assert "data?.success === false" in src
    assert "throw new Error(data?.error" in src
    assert "_libCacheWriteBack()" in src


def test_email_bulk_exports_messages_and_attachments_from_selected_context():
    frontend = email_library_source()
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")
    export_src = _function_source("_exportSelectedBundle")
    payload_src = _function_source("_selectedEmailExportPayload")

    assert "Export Emails" in frontend
    assert "Email file (.eml)" in frontend
    assert "_exportSelectedEmailPdf" in frontend
    assert "Export Attachments" in frontend
    assert "All in view" in frontend
    assert "${isEmailExport ? 'messages' : 'attachments'}-download-bulk" in export_src
    assert "method: 'POST'" in export_src
    assert "res.blob()" in export_src
    assert "account_id: String(em.account_id || state._libAccountId || '')" in payload_src
    assert "folder: String(em.folder || state._libFolder || 'INBOX')" in payload_src

    assert '@router.post("/attachments-download-bulk")' in backend
    assert "Download visible attachments from selected emails as one zip archive." in backend
    assert "_fixture_email_read(uid, folder, owner)" in backend
    assert "_is_likely_signature_image_attachment(att)" in backend

    assert '@router.post("/messages-download-bulk")' in backend
    assert '"(UID RFC822)"' in backend
    assert "msg.as_bytes(policy=email_policy.SMTP)" in backend
    assert 'media_type="message/rfc822"' in backend
    assert '"X-Exported-Emails"' in backend


def test_email_print_pdf_export_reads_without_marking_read_and_sanitizes_body():
    """Print / save PDF export must use the browser print dialog (SAN-157).

    The removed html2pdf library must not be loaded or referenced. Instead
    the export uses a sandboxed iframe and window.print(), matching the
    established pattern in document.js.
    """
    frontend = email_library_source()
    print_src = _function_source("_printSelectedEmails")
    menu_src = js_function_source("_showBulkActionsMenu", frontend)

    assert "mark_seen=false&full=true" in print_src
    assert "_safeRenderEmailBody(data)" in print_src
    assert "new DOMParser()" in print_src
    assert "up to 20 emails" in print_src
    assert "Print / save PDF" in menu_src

    # SAN-157: must NOT reference the removed html2pdf library.
    assert "html2pdf" not in print_src
    assert "html2pdf" not in frontend

    # Must use the browser print pattern with a sandboxed iframe.
    assert "contentWindow.print()" in print_src
    assert "sandbox" in print_src
    assert "allow-same-origin" in print_src
    assert "allow-modals" in print_src
    assert "afterprint" in print_src
    assert "email-browser-print-frame" in print_src


def test_email_eml_export_bounds_total_size():
    """The /messages-download-bulk endpoint must enforce a total size cap
    to prevent unbounded memory growth when exporting many large messages."""
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    assert "max_total_bytes" in backend
    assert "total_bytes" in backend
    assert "Export too large" in backend
    assert "status_code=413" in backend


def test_email_eml_export_validates_selection_count():
    """The /messages-download-bulk endpoint must reject oversized selections."""
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    assert 'len(messages) > 250' in backend
    assert '"Too many emails selected"' in backend


def test_email_eml_export_rejects_non_numeric_remote_uids():
    """Non-numeric UIDs must not be passed to IMAP UID FETCH."""
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    # After fixture lookup fails, non-numeric UIDs are skipped.
    assert 're.fullmatch(r"\\d+", uid)' in backend


def test_email_eml_export_handles_partial_batch_failures():
    """When an IMAP fetch batch returns partial results, exported/skipped
    accounting must remain correct."""
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    # The skipped counter increments for UIDs not found in the batch response.
    assert "skipped += len(batch) - len(found)" in backend
    # Whole-connection failures count remaining unprocessed rows as skipped.
    assert "skipped += remaining_rows" in backend
    assert '"X-Exported-Emails"' in backend
    assert '"X-Skipped-Emails"' in backend


def test_email_eml_export_enforces_account_ownership():
    """The /messages-download-bulk endpoint must assert account ownership."""
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    assert "_assert_owns_account(account_id, owner)" in backend


def test_email_eml_export_deduplicates_selection():
    """Duplicate items in selection must be skipped to avoid duplicate files."""
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    assert "seen_items" in backend


def test_fixture_tag_filter_supports_receipt_tag_flow():
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    assert 'row.get("tags") or row.get("category_tags") or []' in backend
    assert 'elif str(filter_).startswith("tag:"):' in backend
    assert 'rows = [e for e in rows if tag_name in (e.get("tags") or [])]' in backend


def test_email_context_changes_clear_bulk_selection_state():
    """IMAP UIDs are folder/account scoped, so stale bulk selections must die.

    Folder, account, filter, quick-filter, attachment, and search basis changes
    must exit select mode before the next list/search view can run bulk actions.
    """
    text = email_library_source()
    reset_src = _function_source("_resetBulkSelectionForContextChange")
    fresh_src = _function_source("_resetEmailListForFreshLoad")
    add_pill_src = _function_source("_addSearchPill")
    remove_pill_src = _function_source("_removeSearchPillAt")
    search_src = text[text.index("async function _doSearch()"):text.index("// Custom dropdown", text.index("async function _doSearch()"))]

    assert "state._selectedUids.clear()" in reset_src
    assert "state._selectMode = false" in reset_src
    assert "_updateBulkBar()" in reset_src

    assert "_resetBulkSelectionForContextChange()" in fresh_src
    assert "_resetBulkSelectionForContextChange({ rerender: true })" in add_pill_src
    assert "_resetBulkSelectionForContextChange({ rerender: true })" in remove_pill_src
    assert "_resetBulkSelectionForContextChange({ rerender: true })" in search_src

    assert "state._libFolder = _resolveEmailFolderAlias(e.target.value);" in text
    assert "state._libFilter = e.target.value;" in text
    assert "state._libHasAttachments = !state._libHasAttachments;" in text
    assert "const nextAccountId = btn.dataset.accId || null;" in text
    assert "state._libAccountId = nextAccountId;" in text
    assert text.count("_loadEmailsFresh();") >= 5
    assert "state._libSearchDraft = input.value;" in text


def test_email_refresh_uses_explicit_server_refresh_contract():
    """Manual refresh must bypass more than the browser/list response cache.

    The server has a durable index and pooled IMAP handles for speed. The
    refresh button should keep the old rows visible while asking the server to
    evict those fast paths and refetch the visible mailbox slice.
    """
    frontend = email_library_source()
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    assert "refresh=1&_=${Date.now()}" in frontend
    assert "refresh: int = Query(0)" in backend
    assert "manual_refresh = bool(refresh)" in backend
    assert "_invalidate_list_cache(account_id, folder)" in backend
    assert "_invalidate_imap_pool(account_id, owner)" in backend
    assert "cached_rows = {} if refresh else _email_index_rows" in backend


def test_fixture_email_requires_explicit_eval_flag():
    """A leftover fixture file must not replace a user's real mailbox.

    The deterministic fixture mailbox is useful for evals, but production
    routes and MCP tools must not activate it merely because
    data/fixture_email_messages.json exists.
    """
    routes = _EMAIL_ROUTES.read_text(encoding="utf-8")
    mcp = _EMAIL_MCP_SERVER.read_text(encoding="utf-8")
    helper = _EMAIL_FIXTURE_HELPER.read_text(encoding="utf-8")

    guard = 'os.environ.get("ODYSSEUS_EMAIL_FIXTURE") == "1" and _fixture_email_file().exists()'
    assert guard in routes
    assert guard in mcp
    assert 'old_fixture_env = os.environ.get("ODYSSEUS_EMAIL_FIXTURE")' in helper
    assert 'os.environ["ODYSSEUS_EMAIL_FIXTURE"] = "1"' in helper
    assert 'os.environ.pop("ODYSSEUS_EMAIL_FIXTURE", None)' in helper


def test_email_client_cache_drops_fixture_rows():
    """Old fixture rows in browser storage must not keep rendering."""
    frontend = email_library_source()

    assert "function _looksLikeFixtureEmailRow(row)" in frontend
    assert "function _libCacheHasFixtureRows(value)" in frontend
    assert "function _libDropCacheKey(key)" in frontend
    assert "older inbox message" in frontend
    assert "fixture-email-" in frontend
    assert "if (_libCacheHasFixtureRows(memory))" in frontend
    assert "if (_libCacheHasFixtureRows(stored))" in frontend
    assert "if (_libCacheHasFixtureRows(value))" in frontend


def test_email_compose_can_attach_gallery_images():
    """Compose attachments should support local files, documents, and Gallery images."""
    frontend_text = document_source()
    backend = _EMAIL_ROUTES.read_text(encoding="utf-8")

    assert "Upload from computer" in frontend_text
    assert 'data-ody-attach-kind="document"' in frontend_text
    assert "Gallery images" in frontend_text
    assert 'data-ody-attach-kind="gallery"' in frontend_text
    assert "api/gallery/library" in frontend_text
    assert "compose-from-odysseus" in frontend_text

    assert 'kind not in {"document", "gallery"}' in backend
    assert 'if kind == "gallery":' in backend
    assert "GalleryImage" in backend
    assert "_gallery_image_path(img.filename)" in backend
    assert "_stage_compose_file" in backend


class _MockImapConn:
    def __init__(self, messages_by_uid: dict[str, bytes] | None = None, fetch_exc: Exception | None = None):
        self.messages = messages_by_uid or {}
        self.fetch_exc = fetch_exc

    def select(self, folder, readonly=True):
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "FETCH":
            if self.fetch_exc is not None:
                raise self.fetch_exc
            uid_set_b = args[0]
            uid_set = uid_set_b.decode() if isinstance(uid_set_b, bytes) else str(uid_set_b)
            uids = [u.strip() for u in uid_set.split(",") if u.strip()]
            res = []
            for u in uids:
                if u in self.messages:
                    meta = f"1 (UID {u} RFC822 {{{len(self.messages[u])}}}".encode()
                    res.append((meta, self.messages[u]))
                    res.append(b")")
            return "OK", res
        return "NO", []


def _create_test_app(monkeypatch, mailbox: _MockImapConn | None = None, assert_owns_fn=None):
    from contextlib import contextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes.email import email_routes as routes

    conn = mailbox or _MockImapConn()

    @contextmanager
    def mock_imap(account_id=None, owner=""):
        yield conn

    monkeypatch.setattr(routes, "_start_poller", lambda: None)
    monkeypatch.setattr(routes, "_POOL_HOOKS", {})
    monkeypatch.setattr(routes, "_imap", mock_imap)
    if assert_owns_fn:
        monkeypatch.setattr(routes, "_assert_owns_account", assert_owns_fn)

    app = FastAPI()
    app.include_router(routes.setup_email_routes())
    app.dependency_overrides[routes.require_owner] = lambda: "test-user"
    return TestClient(app)


def test_messages_download_bulk_validates_empty_and_oversized_payload(monkeypatch):
    client = _create_test_app(monkeypatch)

    res_empty = client.post("/api/email/messages-download-bulk", json={"messages": []})
    assert res_empty.status_code == 400
    assert "No emails selected" in res_empty.text

    oversized = [{"uid": str(i)} for i in range(251)]
    res_over = client.post("/api/email/messages-download-bulk", json={"messages": oversized})
    assert res_over.status_code == 400
    assert "Too many emails selected" in res_over.text


def test_messages_download_bulk_single_message_eml_export(monkeypatch):
    raw_rfc822 = b"From: sender@example.com\r\nTo: test-user\r\nSubject: Report\r\n\r\nReport content"
    mailbox = _MockImapConn({"101": raw_rfc822})
    client = _create_test_app(monkeypatch, mailbox=mailbox)

    res = client.post("/api/email/messages-download-bulk", json={
        "messages": [{"uid": "101", "subject": "Quarterly Report", "date": "2026-10-20"}]
    })

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("message/rfc822")
    assert res.headers["x-exported-emails"] == "1"
    assert res.headers["x-skipped-emails"] == "0"
    assert "email.eml" in res.headers["content-disposition"]
    assert res.content == raw_rfc822


def test_messages_download_bulk_multi_message_zip_export(monkeypatch):
    import io
    import zipfile

    msg1 = b"From: a@example.com\r\nSubject: First\r\n\r\nOne"
    msg2 = b"From: b@example.com\r\nSubject: Second\r\n\r\nTwo"
    mailbox = _MockImapConn({"101": msg1, "102": msg2})
    client = _create_test_app(monkeypatch, mailbox=mailbox)

    res = client.post("/api/email/messages-download-bulk", json={
        "messages": [
            {"uid": "101", "subject": "First Msg", "date": "2026-10-18"},
            {"uid": "102", "subject": "Second Msg", "date": "2026-10-19"},
        ]
    })

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert res.headers["x-exported-emails"] == "2"
    assert res.headers["x-skipped-emails"] == "0"

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    namelist = zf.namelist()
    assert len(namelist) == 2
    assert any("101.eml" in name for name in namelist)
    assert any("102.eml" in name for name in namelist)


def test_messages_download_bulk_partial_failure_and_duplicate_dedup(monkeypatch):
    import io
    import zipfile

    msg1 = b"From: a@example.com\r\nSubject: Exists\r\n\r\nExists body"
    # UID 101 exists, UID 999 does not exist in mailbox
    mailbox = _MockImapConn({"101": msg1})
    client = _create_test_app(monkeypatch, mailbox=mailbox)

    res = client.post("/api/email/messages-download-bulk", json={
        "messages": [
            {"uid": "101", "subject": "Exists"},
            {"uid": "999", "subject": "Missing"},
            {"uid": "101", "subject": "Duplicate"}, # duplicate must be skipped
        ]
    })

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert res.headers["x-exported-emails"] == "1"
    assert res.headers["x-skipped-emails"] == "2"

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    assert len(zf.namelist()) == 1


def test_messages_download_bulk_enforces_account_ownership_guard(monkeypatch):
    from fastapi import HTTPException

    def mock_assert_owns(account_id, owner):
        if account_id == "other-tenant-acct":
            raise HTTPException(status_code=404, detail="Account not found")

    client = _create_test_app(monkeypatch, assert_owns_fn=mock_assert_owns)

    res = client.post("/api/email/messages-download-bulk", json={
        "messages": [{"uid": "101", "account_id": "other-tenant-acct"}]
    })

    assert res.status_code == 404
    assert "Account not found" in res.text
