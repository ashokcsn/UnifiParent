from PIL import Image

def make_transparent(img_path):
    img = Image.open(img_path)
    img = img.convert("RGBA")
    datas = img.getdata()
    newData = []
    for item in datas:
        if item[0] > 220 and item[1] > 220 and item[2] > 220:
            newData.append((255, 255, 255, 0))
        else:
            newData.append(item)
    img.putdata(newData)
    img.save(img_path, "PNG")

if __name__ == "__main__":
    make_transparent("/data/app/static/favicon.png")
