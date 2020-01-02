FROM python:3.8-slim

WORKDIR /usr/src/app

ENV PGPASSFILE=/opt/.pgpass

RUN mkdir /opt/areas
ENV AREA_ROOT /opt/areas

RUN touch .env

COPY requirements.txt requirements-server.txt ./

RUN pip install --no-cache-dir \
	-r requirements.txt \
	-r requirements-server.txt

COPY dp ./dp

CMD ["python", "-m", "dp.server"]