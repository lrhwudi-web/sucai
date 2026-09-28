"""Local UI review server for salesperson-owned catalog tables."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import json, os, re

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(r'C:\Users\LRH\Documents\New project\work\catalogue-quotes-web\tests\fixtures\catalogue')
PRODUCTS = json.loads((FIXTURE / 'products.json').read_text(encoding='utf-8'))
IMAGES = FIXTURE / 'images'
ADMIN_USER = {'id': 501, 'name': '黄彩丽', 'email': 'sales-a@example.test', 'role': 'admin', 'is_admin': True, 'is_super_admin': False}
CUSTOMER_USER = {'id': 601, 'name': 'FLOG', 'email': 'info@gravityaxis.co.th', 'role': 'overseas_customer', 'is_admin': False, 'is_super_admin': False}
USER = CUSTOMER_USER if os.getenv('PREVIEW_ROLE') == 'customer' else ADMIN_USER
CATALOG = {'owner_user_id': 501, 'owner_name': USER['name'], 'sku_order': [], 'draft': None, 'revision': 0, 'updated_at': None, 'can_manage': True}
LIVE_INVENTORY = {'5902160': 146, '5902211': 27, '7203131': 213, '7203132': 68, '5902287': 81}
LIVE_METRICS = {
    '5900759': (8, 0, 8, 0, 0),
    '5902160': (0, 0, 0, 0, 0),
    '5902211': (0, 0, 0, 0, 0),
    '7203131': (0, 0, 0, 0, 1),
    '7203132': (0, 0, 0, 0, 0),
    '5902287': (0, 0, 0, 0, 0),
}
CUSTOMER_ACCESS = {
    'users': [
        {'id': 601, 'name': 'FLOG', 'email': 'info@gravityaxis.co.th', 'role': 'overseas_customer', 'permission_mode': 'allowlist', 'disabled': 0, 'created_at': '2026-08-28 14:30:00', 'expires_at': '2027-08-28 14:30:00'},
        {'id': 602, 'name': 'Johan', 'email': 'johan@golfgeist.com', 'role': 'overseas_customer', 'permission_mode': 'allowlist', 'disabled': 0, 'created_at': '2026-08-28 14:16:00', 'expires_at': '2027-08-28 14:16:00'},
        {'id': 603, 'name': 'Esteban', 'email': 'bungigolf@gmail.com', 'role': 'overseas_customer', 'permission_mode': 'role_default', 'disabled': 0, 'created_at': '2026-08-07 10:24:00', 'expires_at': '2027-08-07 10:24:00'},
    ],
    'rules': [],
    'user_grants': [
        {'id': 701, 'user_id': 601, 'name': 'FLOG', 'email': 'info@gravityaxis.co.th', 'scope': 'other', 'value': 'Brand Assets', 'created_at': '2026-08-28 14:30:00'},
        {'id': 702, 'user_id': 602, 'name': 'Johan', 'email': 'johan@golfgeist.com', 'scope': 'brand', 'value': 'Craftsman Golf', 'created_at': '2026-08-28 14:16:00'},
    ],
    'permission_values': {'brand': ['Craftsman Golf', 'My Tag'], 'category': [], 'asset_type': ['image', 'video'], 'other': ['Brand Assets', 'Product Catalogs'], 'sku': []},
    'role_labels': {'overseas_customer': '海外客户', 'domestic_customer': '国内客户', 'service_provider': '服务商'},
    'scope_labels': {'brand': '品牌', 'category': '分类', 'asset_type': '素材类型', 'other': '其他标签', 'sku': 'SKU'},
}
ORDERS = {'orders': [
    {'id': 801, 'order_number': 'ORD-20260911-001', 'customer_name': 'FLOG', 'customer_email': 'info@gravityaxis.co.th', 'salesperson_name': ADMIN_USER['name'], 'title': 'September restock', 'company': 'Gravity Axis', 'contact': 'Nina', 'reference': 'PO-0911', 'currency': 'USD', 'product_count': 18, 'total_quantity': 240, 'total_amount_cents': 286500, 'unpriced_count': 0, 'file_name': 'FLOG_2026-09-11.xlsx', 'file_size': 82432, 'notification_status': 'sent', 'status': 'new', 'confirmed_at': '', 'created_at': '2026-09-11 09:38:00', 'download_url': '/api/orders/801/download'},
    {'id': 804, 'order_number': 'ORD-20260826-004', 'customer_name': 'FLOG', 'customer_email': 'info@gravityaxis.co.th', 'salesperson_name': ADMIN_USER['name'], 'title': 'August reorder', 'company': 'Gravity Axis', 'contact': 'Nina', 'reference': 'PO-0826', 'currency': 'USD', 'product_count': 9, 'total_quantity': 120, 'total_amount_cents': 138600, 'unpriced_count': 0, 'file_name': 'FLOG_2026-08-26.xlsx', 'file_size': 61820, 'notification_status': 'sent', 'status': 'confirmed', 'confirmed_at': '2026-08-26 14:18:00', 'created_at': '2026-08-26 14:12:00', 'download_url': '/api/orders/804/download'},
    {'id': 802, 'order_number': 'ORD-20260910-003', 'customer_name': 'Johan', 'customer_email': 'johan@golfgeist.com', 'salesperson_name': ADMIN_USER['name'], 'title': 'Autumn collection', 'company': 'Golfgeist GmbH', 'contact': 'Johan', 'reference': 'GG-260910', 'currency': 'USD', 'product_count': 12, 'total_quantity': 96, 'total_amount_cents': 174800, 'unpriced_count': 2, 'file_name': 'Johan_2026-09-10.xlsx', 'file_size': 65612, 'notification_status': 'sent', 'status': 'new', 'confirmed_at': '', 'created_at': '2026-09-10 16:22:00', 'download_url': '/api/orders/802/download'},
    {'id': 803, 'order_number': 'ORD-20260908-002', 'customer_name': 'Esteban', 'customer_email': 'bungigolf@gmail.com', 'salesperson_name': ADMIN_USER['name'], 'title': 'Sample order', 'company': 'Bungi Golf', 'contact': 'Esteban', 'reference': '', 'currency': 'USD', 'product_count': 6, 'total_quantity': 24, 'total_amount_cents': 49300, 'unpriced_count': 0, 'file_name': 'Esteban_2026-09-08.xlsx', 'file_size': 48210, 'notification_status': 'sent', 'status': 'confirmed', 'confirmed_at': '2026-09-08 11:20:00', 'created_at': '2026-09-08 11:05:00', 'download_url': '/api/orders/803/download'},
]}

for index in range(12):
    month = 8 - index // 4
    day = 24 - (index % 4) * 5
    order_id = 820 + index
    order_number = f"ORD-2026{month:02d}{day:02d}-{index + 5:03d}"
    ORDERS['orders'].append({
        'id': order_id,
        'order_number': order_number,
        'customer_name': 'FLOG',
        'customer_email': 'info@gravityaxis.co.th',
        'salesperson_name': ADMIN_USER['name'],
        'title': f'Preview reorder {index + 1}',
        'company': 'Gravity Axis',
        'contact': 'Nina',
        'reference': f'PO-{month:02d}{day:02d}',
        'currency': 'USD',
        'product_count': 5 + index % 5,
        'total_quantity': 60 + index * 7,
        'total_amount_cents': 82000 + index * 9750,
        'unpriced_count': 0,
        'file_name': f'FLOG_2026-{month:02d}-{day:02d}.xlsx',
        'file_size': 48000 + index * 1200,
        'notification_status': 'sent',
        'status': 'new' if index % 3 == 0 else 'confirmed',
        'confirmed_at': '' if index % 3 == 0 else f'2026-{month:02d}-{day:02d} 11:05:00',
        'created_at': f'2026-{month:02d}-{day:02d} 10:{index:02d}:00',
        'download_url': f'/api/orders/{order_id}/download',
    })

def order_items(count, quantity):
    selected = PRODUCTS[:count]
    base, remainder = divmod(quantity, len(selected))
    return [{
        'sku': product['sku'],
        'name': product['name'],
        'quantity': base + (1 if index < remainder else 0),
        'unit_price_cents': 11800 - index * 350,
        'amount_cents': (base + (1 if index < remainder else 0)) * (11800 - index * 350),
        'image_url': f"/thumb/{product['sku']}",
    } for index, product in enumerate(selected)]

for preview_order in ORDERS['orders']:
    preview_order['items'] = order_items(preview_order['product_count'], preview_order['total_quantity'])

def visible_orders():
    if USER['is_admin']:
        return ORDERS['orders']
    return [order for order in ORDERS['orders'] if order['customer_email'] == USER['email']]

def live_product(product):
    value = LIVE_INVENTORY.get(product['sku'])
    warehouse, age_181_365, age_366_plus, pending_qc, pending_arrival = LIVE_METRICS.get(product['sku'], (0, 0, 0, 0, 0))
    return {
        **product,
        'chinese_name': f"中文品名 {product['sku']}",
        'listing_date': '2025-10-08',
        **({'available_inventory': value} if value is not None else {}),
        'sales_warehouse_name': USER['name'],
        'sales_warehouse_inventory': warehouse,
        'sales_warehouse_age_181_365': age_181_365,
        'sales_warehouse_age_366_plus': age_366_plus,
        'total_pending_qc': pending_qc,
        'total_pending_arrival': pending_arrival,
        'inventory_state': 'live',
        'inventory_updated_at': '2026-09-08T09:18:22',
    }

def preview_assets(product):
    return [{
        'id': product['sku'],
        'name': product['name'],
        'kind': 'image',
        'mime_type': 'image/jpeg',
        'size': (IMAGES / f"{product['sku']}.jpg").stat().st_size,
        'modified_time': '2026-09-07T12:00:00Z',
        'path': f"preview/{product['sku']}.jpg",
        'asset_type': 'image',
        'internal_only': False,
        'thumbnail_url': f"/thumb/{product['sku']}",
        'preview_url': f"/media/{product['sku']}",
        'download_url': f"/download/{product['sku']}",
    }]

class Preview(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(ROOT/'dist'), **kwargs)
    def send_json(self, value, status=200):
        body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        url=urlparse(self.path);route=unquote(url.path);query=parse_qs(url.query)
        if route=='/api/session':return self.send_json({'user':USER})
        if route=='/api/catalog-order':return self.send_json(CATALOG)
        if route=='/api/themes':return self.send_json({'themes':[]})
        if route=='/api/admin/notifications':return self.send_json({'pending_count':0})
        if route=='/api/admin/access-control':return self.send_json(CUSTOMER_ACCESS)
        if route=='/api/orders':return self.send_json({'orders': visible_orders()})
        order_detail=re.fullmatch(r'/api/orders/(\d+)',route)
        if order_detail:
            order=next((item for item in visible_orders() if item['id']==int(order_detail.group(1))),None)
            return self.send_json({'order':order}) if order else self.send_json({'detail':'Order not found'},404)
        order_download=re.fullmatch(r'/api/orders/(\d+)/download',route)
        if order_download:
            order=next((item for item in ORDERS['orders'] if item['id']==int(order_download.group(1))),None)
            if not order:return self.send_json({'detail':'Order not found'},404)
            order.update({'status':'confirmed','confirmed_at':'2026-09-11 11:30:00'})
            body=b'Preview Excel download'
            self.send_response(200);self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');self.send_header('Content-Disposition',f'attachment; filename="{order["file_name"]}"');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        if route=='/api/products':
            offset=int(query.get('offset',['0'])[0]);limit=int(query.get('limit',['250'])[0])
            return self.send_json({'products':[live_product(product) for product in PRODUCTS[offset:offset+limit]],'total':len(PRODUCTS),'next_offset':offset+limit,'has_more':offset+limit<len(PRODUCTS)})
        if re.fullmatch(r'/api/products/\d+',route):
            sku=route.rsplit('/',1)[-1];product=next((p for p in PRODUCTS if p['sku']==sku),None)
            if not product:return self.send_json({'detail':'Product not found'},404)
            return self.send_json({'product':{**live_product(product),'assets':preview_assets(product),'image_count':1,'file_count':1}})
        image_match=re.fullmatch(r'/(thumb|media|download)/(\d+)',route)
        if image_match:
            kind,sku=image_match.groups();path=IMAGES/f'{sku}.jpg'
            if not path.exists():return self.send_json({'detail':'Image not found'},404)
            body=path.read_bytes();self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Cache-Control','public, max-age=3600');self.send_header('Content-Length',str(len(body)))
            if kind=='download':self.send_header('Content-Disposition',f'attachment; filename="{sku}.jpg"')
            self.end_headers();self.wfile.write(body);return
        if route.startswith(('/api/','/sku/')):return self.send_json({'detail':'Unavailable in local review.'},404)
        return super().do_GET()
    def do_PUT(self):
        if urlparse(self.path).path!='/api/catalog-order':return self.send_json({'detail':'Not found'},404)
        length=int(self.headers.get('Content-Length','0'));payload=json.loads(self.rfile.read(length))
        if payload.get('revision')!=CATALOG['revision']:return self.send_json({'detail':'Catalog order changed in another browser.'},409)
        CATALOG.update({'sku_order':payload['sku_order'],'draft':payload['draft'],'revision':CATALOG['revision']+1,'updated_at':'2026-09-07T12:00:00','can_manage':True})
        return self.send_json(CATALOG)
    def do_POST(self):
        if urlparse(self.path).path=='/api/catalogue/missing-skus':return self.send_json({'notified':True,'duplicate':False,'recipient_name':'刘芮华'})
        if self.path.endswith('/favorite'):return self.send_json({'is_favorite':True})
        return self.send_json({'detail':'Unavailable in local review.'},400)

if __name__=='__main__':
    print('Sales catalog preview: http://127.0.0.1:4187/#quotation',flush=True)
    ThreadingHTTPServer(('127.0.0.1',4187),Preview).serve_forever()
