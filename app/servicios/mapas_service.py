"""Google Maps links and road routing; API credentials stay on the server."""
import math
import re
from urllib.parse import urlparse,parse_qs,urljoin,unquote,unquote_plus
import httpx
from fastapi import HTTPException
from app.configuracion import settings


def validate_link(link):
    try: parsed=urlparse(link.strip())
    except ValueError: raise HTTPException(422,'El enlace de Google Maps no es válido.')
    hosts={'google.com','www.google.com','maps.google.com','www.google.com.bo','maps.google.com.bo','maps.app.goo.gl','goo.gl'}
    try: port=parsed.port
    except ValueError: raise HTTPException(422,'El enlace de Google Maps no es válido.')
    if parsed.scheme!='https' or parsed.hostname not in hosts or parsed.username or parsed.password or port not in (None,443):
        raise HTTPException(422,'Pega un enlace HTTPS de Google Maps, por ejemplo el enlace de Compartir ubicación.')
    if parsed.hostname=='goo.gl' and not parsed.path.startswith('/maps/'):
        raise HTTPException(422,'El enlace debe ser de Google Maps.')
    return link.strip()


def coordinates(link):
    text=unquote(link)
    pair=r'(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)'
    pinned=re.search(r'!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)',text)
    query=parse_qs(urlparse(link).query)
    match=pinned
    if not match:
        for field in ('query','q','destination','ll'):
            match=re.fullmatch(pair,query.get(field,[''])[0])
            if match:break
    if not match:
        # Shared mobile pins can redirect to /maps/search/LAT,+LON rather
        # than placing coordinates in q= or @LAT,LON.
        path=unquote_plus(urlparse(link).path)
        match=re.search(r'/maps/(?:search|place)/'+pair+r'(?:/|$)',path)
    if not match:match=re.search('@'+pair,text)
    if not match:return None
    lat,lon=map(float,match.groups())
    if not (-90<=lat<=90 and -180<=lon<=180):raise HTTPException(422,'La ubicación contiene coordenadas inválidas.')
    return lat,lon


def resolve(link):
    link=validate_link(link)
    point=coordinates(link)
    if point:return point
    try:
        with httpx.Client(timeout=6,follow_redirects=False) as client:
            current=link
            for _ in range(5):
                validate_link(current)
                point=coordinates(current)
                if point:return point
                with client.stream('GET',current,headers={'User-Agent':'VESTA-Delivery/1.0'}) as response:
                    if response.is_redirect:
                        current=urljoin(current,response.headers.get('location',''))
                        continue
                    response.raise_for_status()
                    content=b''
                    for chunk in response.iter_bytes():
                        content+=chunk
                        if len(content)>65536:break
                    html=content.decode('utf-8',errors='ignore')
                    for target in re.findall(r'https://[^\s"<>]+',html):
                        try:
                            validate_link(target)
                            point=coordinates(target)
                            if point:return point
                        except HTTPException:continue
                    break
            query=parse_qs(urlparse(current).query)
            address=query.get('query',query.get('q',[None]))[0]
            place=query.get('query_place_id',[None])[0]
            if settings.GOOGLE_MAPS_API_KEY and (address or place):
                params={'key':settings.GOOGLE_MAPS_API_KEY,**({'place_id':place} if place else {'address':address})}
                result=client.get('https://maps.googleapis.com/maps/api/geocode/json',params=params)
                result.raise_for_status();data=result.json()
                if data.get('status')=='OK':
                    point=data['results'][0]['geometry']['location']
                    return float(point['lat']),float(point['lng'])
    except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
        raise HTTPException(502,'No se pudo abrir Google Maps. Reintenta o comparte el enlace de un pin con coordenadas.')
    raise HTTPException(422,'No se pudo ubicar el punto del enlace. En Google Maps mantén pulsado el lugar, elige Compartir y copia el enlace del pin.')


def route(origin,destination):
    try:
        if settings.GOOGLE_MAPS_API_KEY:
            point=lambda p:{'location':{'latLng':{'latitude':p[0],'longitude':p[1]}}}
            response=httpx.post('https://routes.googleapis.com/directions/v2:computeRoutes',
                headers={'X-Goog-Api-Key':settings.GOOGLE_MAPS_API_KEY,'X-Goog-FieldMask':'routes.distanceMeters,routes.duration'},
                json={'origin':point(origin),'destination':point(destination),'travelMode':'DRIVE','routingPreference':'TRAFFIC_UNAWARE'},timeout=12)
            response.raise_for_status();rows=response.json().get('routes',[])
            if not rows:raise ValueError()
            distance=float(rows[0]['distanceMeters']);duration=float(rows[0]['duration'].removesuffix('s'));provider='GOOGLE_ROUTES'
        elif settings.DELIVERY_OSRM_URL:
            coordinates_path=f'{origin[1]},{origin[0]};{destination[1]},{destination[0]}'
            response=httpx.get(settings.DELIVERY_OSRM_URL.rstrip('/')+'/route/v1/driving/'+coordinates_path,
                params={'overview':'false','alternatives':'false','steps':'false'},timeout=12)
            response.raise_for_status();rows=response.json().get('routes',[])
            if not rows:raise ValueError()
            distance=float(rows[0]['distance']);duration=float(rows[0]['duration']);provider='OSRM'
        else:
            raise HTTPException(503,'Configura GOOGLE_MAPS_API_KEY con Routes API o DELIVERY_OSRM_URL para calcular distancia y tiempo por calles.')
        if not all(math.isfinite(n) and n>=0 for n in (distance,duration)):raise ValueError()
        return math.ceil(distance),math.ceil(duration),provider
    except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
        raise HTTPException(502,'No se pudo calcular una ruta por calles entre la sucursal y el destino. Revisa los puntos y reintenta.')
