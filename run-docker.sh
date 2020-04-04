docker build . -t feedmixer
docker run -p 8000:8000 --name fm feedmixer