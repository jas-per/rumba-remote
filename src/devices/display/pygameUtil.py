import pygame


# Helper func to create rounded rectangles
def roundRect(size, color, rad=20, corners=None, border=0):
    """
        Draw a rect with rounded corners to surface.
        Argument rad can be specified to adjust curvature of edges (given in pixels)
    """
    if corners is None:
        corners = ["topleft", "topright", "bottomleft", "bottomright"]
    if border > 0:
        outerSize = size
        size = (size[0] - (border * 2), size[1] - (border * 2))

    image = pygame.Surface(size).convert_alpha()
    image.fill((0, 0, 0, 0))

    rect = pygame.Rect((0, 0), size)
    cornerPos = rect.inflate(-2 * rad, -2 * rad)
    for corner in ["topleft", "topright", "bottomleft", "bottomright"]:
        if corner in corners:
            pygame.draw.circle(image, color, getattr(cornerPos, corner), rad)
        else:
            pos = getattr(cornerPos, corner)
            if corner[:3] == 'top':
                pos = (pos[0], pos[1] - rad)
            if corner[-4:] == 'left':
                pos = (pos[0] - rad, pos[1])
            pygame.draw.rect(image, color, pygame.Rect(pos, (rad, rad)))
    image.fill(color, rect.inflate(-2 * rad, 0))
    image.fill(color, rect.inflate(0, -2 * rad))

    if border > 0:
        bgimage = roundRect(outerSize, (0, 0, 0), rad, corners)  # black border
        bgimage.blit(image, (border, border))
        return bgimage
    return image


# aspect_scale.py - Scaling surfaces to height while mostly keeping
# their aspect ratio, centered on vertical black background if neccessary
# ©Frank Raiser / public domain > http://www.pygame.org/pcr/transform_scale/
def aspectScale(img, maxDim, background=True):
    """ Scales 'img' to fit into box bx/by.
     This method will retain the original image's aspect ratio """
    bx, by = maxDim
    ix, iy = img.get_size()
    if ix > iy:
        return pygame.transform.smoothscale(img, maxDim)

    # fit to height
    scaleFactor = by / iy
    sx = scaleFactor * ix
    if sx > bx:
        scaleFactor = bx / ix
        sx = bx
        sy = scaleFactor * iy
    else:
        sy = by
    img = pygame.transform.smoothscale(img, (int(sx), int(sy)))
    if background:
        bg = pygame.Surface(maxDim)
        bg.fill((0, 0, 0))
        bg.blit(img, (int((maxDim[0] - sx) / 2), 0))
        return bg

    return img
