"""Integration gate; run inside the backend container after forms.demo and Playwright."""
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import get_session
from app.modules.sync.models import CollectionDraft, DraftAttachment, SyncOperation
from app.modules.sync.storage import client as storage_client


def main():
    credentials = json.loads(Path('/app/.local/forms-demo.json').read_text())
    headers = {'Authorization': 'Bearer ' + credentials['token']}
    base = 'http://localhost:8000'
    with httpx.Client(base_url=base, headers=headers, timeout=30) as api:
        versions = api.get(f"/api/forms/{credentials['form_id']}/versions").json()
        version = next(v for v in versions if v['status'] == 'PUBLISHED')
        grant = api.post(f"/api/sync/grants/{version['id']}")
        grant.raise_for_status()
        content = b'%PDF-1.4\nSynchroHQ concurrent evidence\n%%EOF'
        attachment_id = str(uuid.uuid4())
        metadata = {'attachment_id': attachment_id, 'file_name': 'concurrent.pdf',
                    'mime_type': 'application/pdf', 'size': len(content),
                    'sha256': hashlib.sha256(content).hexdigest()}
        body = {'operation_id': str(uuid.uuid4()), 'draft_id': str(uuid.uuid4()),
                'device_id': str(uuid.uuid4()), 'form_version_id': version['id'],
                'base_version': 0, 'client_updated_at': datetime.now(UTC).isoformat(),
                'answers': {'attachments': [metadata]}, 'sync_grant': grant.json()['sync_grant']}
        def draft_send(_):
            result = api.post('/api/sync/drafts', json=body)
            result.raise_for_status()
            return result.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(draft_send, range(2)))
        assert receipts[0] == receipts[1]
        path = f"/api/sync/drafts/{body['draft_id']}/attachments/{attachment_id}"
        data = {k: str(v) for k, v in metadata.items() if k != 'attachment_id'}
        def file_send(_):
            result = api.put(path, data=data,
                             files={'file': ('concurrent.pdf', content, 'application/pdf')})
            result.raise_for_status()
            return result.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(file_send, range(2)))
        assert receipts[0] == receipts[1]
    session_iterator = get_session()
    session = next(session_iterator)
    try:
        draft_id = uuid.UUID(body['draft_id'])
        assert session.scalar(select(func.count()).select_from(CollectionDraft).where(CollectionDraft.id == draft_id)) == 1
        assert session.scalar(select(func.count()).select_from(SyncOperation).where(SyncOperation.draft_id == draft_id)) == 1
        attachments = session.scalars(select(DraftAttachment).where(DraftAttachment.draft_id == draft_id)).all()
        assert len(attachments) == 1
        browser_file = session.scalars(select(DraftAttachment).where(DraftAttachment.file_name == 'preuve-offline.pdf').order_by(DraftAttachment.received_at.desc())).first()
        assert browser_file is not None, 'Browser offline attachment was not received'
        storage = storage_client()
        for item, expected in [(attachments[0], content), (browser_file, b'%PDF-1.4\nSynchroHQ offline evidence\n%%EOF')]:
            result = storage.get_object(Bucket=get_settings().s3_bucket, Key=item.storage_key)
            with result['Body'] as stream:
                actual = stream.read()
            assert actual == expected
            assert len(actual) == item.size
            assert hashlib.sha256(actual).hexdigest() == item.sha256
        print('PASS: concurrent draft and attachment retries return identical receipts; one database record each.')
        print('PASS: browser offline attachment and concurrent upload bytes verified in MinIO (SHA-256).')
    finally:
        session_iterator.close()


if __name__ == '__main__':
    main()
