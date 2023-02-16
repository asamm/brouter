package btools.mapcreator;

import org.junit.Assert;
import org.junit.Test;

import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.net.URL;
import java.util.ArrayList;

public class ElevationComputeTest {

  @Test
  public void testCustomTrackElevation() throws Exception {
    URL dataUrl = this.getClass().getResource("/coordinates.csv");
    Assert.assertNotNull("coordinates.csv not found", dataUrl);
    File dataFile = new File(dataUrl.getFile());
    FileInputStream fis = new FileInputStream(dataFile);
    DataInputStream dis = new DataInputStream(fis);
    ArrayList<PosUnifierTest.Coord> coords = new ArrayList<>();
    while (true) {
      String line = dis.readLine();
      if (line == null || line.isBlank()) {
        break;
      }
      String[] items = line.split("\t");
      coords.add(new PosUnifierTest.Coord(Double.parseDouble(items[1]), Double.parseDouble(items[0])));
    }
    System.out.println("Loaded " + coords.size() + " coordinates");

    PosUnifier unifier = new PosUnifier();
    unifier.resetSrtm();
    unifier.setSrtmdir(System.getenv("SRTM_FILES_ROOT_ESRI_ASAMM"));
    for (PosUnifierTest.Coord coord : coords) {
      int ilon = (int) ((coord.lon + 180.) * 1000000. + 0.5);
      int ilat = (int) ((coord.lat + 90.) * 1000000. + 0.5);
      SrtmRaster raster = unifier.srtmForNode(ilon, ilat);
      // false is default in brouter for tiles with cols < 6001
      // raster.usingWeights = raster.ncols > 6001;
      raster.usingWeights = true;
      coord.elev = raster.getElevation(ilon, ilat) / 4.0;
      System.out.println(coord.lon + ";" + coord.lat + ";" + coord.elev);
    }
  }
}
