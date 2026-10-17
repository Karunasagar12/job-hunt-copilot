import base64

from api.app import _signature_to_cid


def test_signature_fixture_preserves_embedded_image_cids():
    from io import BytesIO
    from PIL import Image

    image = BytesIO()
    Image.new('RGB', (1, 1), 'white').save(image, format='PNG')
    encoded = base64.b64encode(image.getvalue()).decode('ascii')
    html = '<body>\n<div>Jane<br>' + ''.join(
        f'<img src="data:image/png;base64,{encoded}">' for _ in range(4)
    ) + '</div>\n</body>'
    converted, images = _signature_to_cid(html)
    assert len(images) == 4 and converted.count('cid:') == 4
    assert '<br>' in converted


def test_converts_two_embedded_png_images():
    first = base64.b64encode(b"first").decode("ascii")
    second = base64.b64encode(b"second").decode("ascii")
    html = (
        f'<div><img src="data:image/png;base64,{first}">'
        f'<span>x</span><img src="data:image/png;base64,{second}"></div>'
    )

    converted, attachments = _signature_to_cid(html)

    assert converted == (
        '<div><img src="cid:signature-image-0@jobhunt.local">'
        '<span>x</span><img src="cid:signature-image-1@jobhunt.local"></div>'
    )
    assert attachments == [
        {"filename": "signature-0.png", "content_type": "image/png", "content": first,
         "content_disposition": "inline", "content_id": "signature-image-0@jobhunt.local"},
        {"filename": "signature-1.png", "content_type": "image/png", "content": second,
         "content_disposition": "inline", "content_id": "signature-image-1@jobhunt.local"},
    ]


def test_without_embedded_images_returns_unchanged():
    html = '<div><img src="https://example.com/image.png"><p>No embedded images</p></div>'

    converted, attachments = _signature_to_cid(html)

    assert converted == html
    assert attachments == []


def test_supports_png_jpeg_and_gif():
    png = base64.b64encode(b"p").decode("ascii")
    jpg = base64.b64encode(b"j").decode("ascii")
    gif = base64.b64encode(b"g").decode("ascii")
    html = (
        f'<img src="data:image/png;base64,{png}">'
        f'<img src="data:image/jpeg;base64,{jpg}">'
        f'<img src="data:image/gif;base64,{gif}">'
    )

    _, attachments = _signature_to_cid(html)

    assert [a["filename"] for a in attachments] == [
        "signature-0.png", "signature-1.jpg", "signature-2.gif",
    ]


if __name__ == "__main__":
    test_converts_two_embedded_png_images()
    test_without_embedded_images_returns_unchanged()
    test_supports_png_jpeg_and_gif()
    print("test_signature_to_cid: all checks passed")
