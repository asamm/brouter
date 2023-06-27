package btools.mapcreator;

import org.junit.Assert;
import org.junit.Ignore;
import org.junit.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

public class PosUnifierTest {

  @Test
  public void testHgtFileNameComposition() {
    int[] lats = {-90, -89, -1, -0, 0, 1, 89, 90, 0, 0, -1, -1};
    int[] lons = {-180, -179, -1, -0, 0, 1, 179, 180, 0, -1, -1, 0};
    String[] expected = {
      "S90W180",
      "S89W179",
      "S01W001",
      "N00E000",
      "N00E000",
      "N01E001",
      "N89E179",
      "N90E180",
      "N00E000",
      "N00W001",
      "S01W001",
      "S01E000"
    };
    PosUnifier unifier = new PosUnifier();
    for (int i = 0; i < expected.length; i++) {
      String tile = unifier.hgtFileName(lons[i], lats[i]);
      assert (tile.length() == 7);
      assert (tile.equals(expected[i]));
      System.out.println(tile);
    }
  }

  @Test
  public void testIndexingOfDoubleValues() {
    double[] coords = {-180.0, -179.5, -1.5, -1.0, -0.5, 0.0, 0.1, 1.5, 179.9, 180.0}; // 180.0 exactly: there is no tile 180E
    int[] expected = {-180, -180, -2, -1, -1, 0, 0, 1, 179, 179};
    PosUnifier unifier = new PosUnifier();
    for (int i = 0; i < expected.length; i++) {
      assert (unifier.indexHgt(coords[i], 180.0) == expected[i]);
    }
  }

  @Test
  public void testConversionCoordinates() {
    double coord = -180.0;
    PosUnifier unifier = new PosUnifier();
    while (coord < 180.0) {
      NodeData nd = new NodeData(1, coord, coord);
      assert (Math.abs(unifier.doublelat(nd.ilat) - coord) < 1E-5);
      assert (Math.abs(unifier.doublelon(nd.ilon) - coord) < 1E-5);
      coord += 0.00001;
    }
  }

  // integration test - test data generation part
  // the idea here is to query PosUnifier with coordinates in ilat, ilon format,
  // then query again returned SrtmRasterObject for coordinates in double format
  // print values in .csv format so we can assert values with Asamm library for .hgt files

  //
  // ilat = (int)( ( lat + 90. )*1000000. + 0.5);
  // ilon = (int)( ( lon + 180. )*1000000. + 0.5);
  //

  private final List<Coord> coords = new ArrayList();

  private void addCases() {

    double[] lats = {48.0, 48.0, 49.0, 49.0, 51.0, 51.0, 52.0, 52.0, 52.5, 52.5, 52.5, -72.5, -72.5, -72.5, 51.0, 51.0, 52.0, 52.0, 52.2, 0.0, 1.0E-4, -1.0E-4, -13.0, -13.0, -14.0, -14.0, -14.2, -33.0, -33.0, -34.0, -34.0, -34.2, 36.0, 36.0, 37.0, 37.0, 37.2, 66.0, 66.0, 66.0, 66.0, 66.0, -29.0, -29.0, -30.0, -30.0};
    double[] lons = {12.0, 13.0, 12.0, 13.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0E-4, -1.0E-4, 0.0, 1.0E-4, -1.0E-4, 0.0, -1.0, 0.0, -1.0, -1.2, 23.0, 23.0, 23.0, 23.0, 24.0, 23.0, 24.0, 24.2, -67.0, -68.0, -67.0, -68.0, -68.2, -101.0, -102.0, -101.0, -102.0, -102.2, 180.0, 179.0, 179.999, -179.999, -179.999, 141.0, 142.0, 141.0, 142.0};
    Assert.assertEquals(lats.length, lons.length);
    double[] elevs = {486.0, 425.0, 414.0, 537.0, 24.0, 0.0};

    for (int i = 0; i < lats.length; i++) {
      Coord c = new Coord(lats[i], lons[i]);
      if (i < elevs.length) c.expectedElev = elevs[i];
      coords.add(c);
    }
  }

  private void addRandom(int n) {
    Random rnd = new Random();
    int count = 0;
    while (count < n) {
      coords.add(new Coord(43.0 + rnd.nextDouble() * 10.0, 19.0 + rnd.nextDouble() * 10.0));
      count++;
    }
  }

  @Test
  public void buildIntegrationTestData() throws Exception {
    addCases();
    addRandom(100);
    PosUnifier unifier = new PosUnifier();
    unifier.resetSrtm();
    unifier.setSrtmdir(System.getenv("SRTM_FILES_ROOT_ESRI_ASAMM"));
    for (Coord coord : coords) {
      int ilat = (int) ((coord.lat + 90.) * 1000000. + 0.5);
      int ilon = (int) ((coord.lon + 180.) * 1000000. + 0.5);
      SrtmRaster raster = unifier.srtmForNode(ilon, ilat);
      raster.usingWeights = false;
      coord.elev = raster.getElevation(ilon, ilat) / 4.0;
    }
    // assert at least a few cases, expected values computed by https://www.gpsvisualizer.com/elevation
    double okDiff = 2.0;
    for (Coord coord : coords) {
      double diff = Math.abs(coord.elev - coord.expectedElev);
      if (coord.expectedElev != -1.1 && diff > okDiff) {
        System.out.println("Assertion fail for: " + coord.toRichString());
        assert false;
      }
    }
    // output
    for (Coord coord : coords) {
      System.out.println(coord.toString());
    }
  }

  @Test
  @Ignore
  public void printFirstRow() throws Exception {
    PosUnifier unifier = new PosUnifier();
    unifier.resetSrtm();
    unifier.setSrtmdir(System.getenv("SRTM_FILES_ROOT_ESRI_ASAMM"));
    int ilat = (int) ((48.0 + 90.) * 1000000. + 0.5);
    int ilon = (int) ((12.0 + 180.) * 1000000. + 0.5);
    SrtmRaster raster = unifier.srtmForNode(ilon, ilat);
    raster.usingWeights = false;
    for (int i = 0; i < 1203; i++) {
      System.out.print(raster.eval_array[i] + " ");
    }
  }

  static class Coord {
    protected Coord(double lat, double lon) {
      this.lat = lat;
      this.lon = lon;
    }

    double lat;
    double lon;
    double elev;
    double expectedElev = -1.1;

    @Override
    public String toString() {
      return this.lat + "," + this.lon + "," + this.elev;
    }

    public String toRichString() {
      return "lat: " + this.lat + ", lon: " + this.lon + ", elev: " + this.elev + ", expected elev: " + this.expectedElev;
    }
  }
}
