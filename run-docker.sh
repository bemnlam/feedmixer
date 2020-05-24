docker build . -t feedmixer
# map guest's port 8000 to host's port 80
docker run -p 80:8000 --name fm feedmixer