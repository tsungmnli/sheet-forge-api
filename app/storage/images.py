"""이미지 저장소. 운영은 MinIO(S3 호환), 개발·테스트는 메모리. ref는 `img_<ULID>`(불투명 값)이고 객체 키로 그대로 쓴다."""
import io


class StorageError(Exception):
    """저장소에 닿지 못했을 때. 이미지 내용은 오류에 담지 않는다."""


class ImageStore:
    def put(self, ref: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    def get(self, ref: str):
        """(bytes, content_type) 또는 없으면 None."""
        raise NotImplementedError

    def delete(self, ref: str) -> None:
        raise NotImplementedError

    def check(self) -> None:
        """readiness용. 닿지 못하면 예외."""
        raise NotImplementedError


class MemoryImageStore(ImageStore):
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, ref, data, content_type):
        self.objects[ref] = (bytes(data), content_type)

    def get(self, ref):
        return self.objects.get(ref)

    def delete(self, ref):
        self.objects.pop(ref, None)

    def check(self):
        return None


class MinioImageStore(ImageStore):
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str, secure: bool = False):
        import urllib3
        from minio import Minio
        http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=3.0, read=30.0),
                                   retries=urllib3.Retry(total=1, backoff_factor=0.2))
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure, http_client=http)
        self._bucket = bucket
        self._ready = False

    def _ensure(self) -> None:
        if self._ready:
            return
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
        except Exception as e:  # noqa: BLE001
            raise StorageError(type(e).__name__) from e
        self._ready = True

    def put(self, ref, data, content_type):
        self._ensure()
        try:
            self._client.put_object(self._bucket, ref, io.BytesIO(data), len(data), content_type=content_type)
        except Exception as e:  # noqa: BLE001
            raise StorageError(type(e).__name__) from e

    def get(self, ref):
        from minio.error import S3Error
        self._ensure()
        try:
            resp = self._client.get_object(self._bucket, ref)
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchObject"):
                return None
            raise StorageError(e.code) from e
        except Exception as e:  # noqa: BLE001
            raise StorageError(type(e).__name__) from e
        try:
            return resp.read(), resp.headers.get("Content-Type", "application/octet-stream")
        except Exception as e:  # noqa: BLE001
            raise StorageError(type(e).__name__) from e
        finally:
            resp.close()
            resp.release_conn()

    def delete(self, ref):
        self._ensure()
        try:
            self._client.remove_object(self._bucket, ref)
        except Exception as e:  # noqa: BLE001
            raise StorageError(type(e).__name__) from e

    def check(self):
        self._ensure()


def build_store(settings):
    """MinIO 주소가 없으면 None(사진 API는 503, 나머지는 그대로 동작)."""
    if not settings.minio_endpoint:
        return None
    return MinioImageStore(settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key,
                           settings.minio_bucket, settings.minio_secure)
